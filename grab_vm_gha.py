# -*- coding: utf-8 -*-
"""
GitHub Actions 版搶機腳本 - 從環境變數讀取 OCI 憑證
每次 Actions job 約跑 4 分鐘，配合 cron */5 達到近乎連續搶機
"""
import time, os, tempfile, urllib.request, urllib.parse
import oci

# 從 GitHub Secrets / 環境變數讀取
OCI_USER        = os.environ["OCI_USER"]
OCI_FINGERPRINT = os.environ["OCI_FINGERPRINT"]
OCI_TENANCY     = os.environ["OCI_TENANCY"]
OCI_REGION      = os.environ["OCI_REGION"]
OCI_KEY_CONTENT = os.environ["OCI_KEY_CONTENT"]
SUBNET_ID       = os.environ["SUBNET_ID"]
AD              = os.environ["AD"]
IMAGE_ID        = os.environ["IMAGE_ID"]
SSH_PUB_KEY     = os.environ["SSH_PUB_KEY"]
TG_TOKEN        = os.environ["TG_TOKEN"]
TG_CHAT         = os.environ["TG_CHAT"]
LABEL           = os.environ.get("LABEL", "GHA")  # 標記來自哪條線

# 把 key 寫入暫存檔
_kf = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w")
_kf.write(OCI_KEY_CONTENT)
_kf.close()

config = {
    "user": OCI_USER,
    "fingerprint": OCI_FINGERPRINT,
    "tenancy": OCI_TENANCY,
    "region": OCI_REGION,
    "key_file": _kf.name,
}
oci.config.validate_config(config)

def tg(msg):
    try:
        url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": msg}).encode()
        urllib.request.urlopen(url, data=data, timeout=10)
    except:
        pass

def log(msg):
    import datetime
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def main():
    compute = oci.core.ComputeClient(config)
    log(f"=== [{LABEL}] 搶機開始 | Region: {OCI_REGION} | AD: {AD} ===")

    # 每次 job 跑 6 分鐘（配合 cron */10），每 30 秒嘗試一次
    JOB_MINUTES = 6
    INTERVAL    = 30
    MAX_ROUNDS  = (JOB_MINUTES * 60) // INTERVAL

    for count in range(1, MAX_ROUNDS + 1):
        log(f"[第 {count}/{MAX_ROUNDS} 次] 嘗試建立 VM...")
        try:
            detail = oci.core.models.LaunchInstanceDetails(
                availability_domain=AD,
                compartment_id=OCI_TENANCY,
                display_name="hao-bot",
                image_id=IMAGE_ID,
                shape="VM.Standard.A1.Flex",
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=1, memory_in_gbs=6
                ),
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=SUBNET_ID,
                    assign_public_ip=True
                ),
                metadata={"ssh_authorized_keys": SSH_PUB_KEY}
            )
            resp     = compute.launch_instance(detail)
            instance = resp.data
            log(f"VM 建立成功！ID: {instance.id}")

            for _ in range(30):
                time.sleep(10)
                try:
                    vnics = compute.list_vnic_attachments(OCI_TENANCY, instance_id=instance.id)
                    if vnics.data:
                        vnic_id = vnics.data[0].vnic_id
                        network = oci.core.VirtualNetworkClient(config)
                        vnic    = network.get_vnic(vnic_id).data
                        if vnic.public_ip:
                            log(f"Public IP: {vnic.public_ip}")
                            tg(
                                f"🎉 [{LABEL}] Oracle VM 搶到了！\n"
                                f"Region: {OCI_REGION}\n"
                                f"Public IP: {vnic.public_ip}\n\n"
                                f"SSH 指令：\nssh -i ~/.ssh/oracle_hao_bot ubuntu@{vnic.public_ip}"
                            )
                            return
                except Exception as e:
                    log(f"取 IP 中... {e}")

            tg(f"[{LABEL}] VM 建立成功但未取得 IP，請到 Console 查看")
            return

        except oci.exceptions.ServiceError as e:
            if e.status in (500, 429) or "capacity" in (e.message or "").lower():
                log(f"  容量不足 ({e.status})，{INTERVAL} 秒後重試...")
            else:
                log(f"  錯誤 ({e.status}): {(e.message or '')[:80]}，{INTERVAL} 秒後重試...")
        except Exception as e:
            log(f"  未知錯誤: {str(e)[:80]}，{INTERVAL} 秒後重試...")

        if count < MAX_ROUNDS:
            time.sleep(INTERVAL)

    log(f"[{LABEL}] 本次 job 結束，等待下次排程...")

if __name__ == "__main__":
    main()

import os
import requests

BASE = os.environ.get("SRA_API_BASE", "http://192.168.0.133:9002")
OPENWEBUI_KEY = os.environ["SRA_SMOKE_OPENWEBUI_KEY"]
READ_ONLY_KEY = os.environ["SRA_SMOKE_READONLY_KEY"]
REPORT_KEY = os.environ["SRA_SMOKE_REPORT_KEY"]


def show(name, response):
    print()
    print("=" * 70)
    print(name)
    print("HTTP:", response.status_code)

    try:
        print(response.json())
    except Exception:
        print(response.text[:1000])

####read_only_test############################################################

headers = {
    "Authorization": f"Bearer {READ_ONLY_KEY}"
}

r = requests.get(
    f"{BASE}/v1/models",
    headers=headers,
)

print("read test code for READ_ONLY_KEY: ",r.status_code)


r = requests.post(
    f"{BASE}/v1/chat/completions",
    headers=headers,
    json={
        "model": "SRA-Structured Retrieval Agent",
        "messages": [
            {
                "role": "user",
                "content": "test"
            }
        ]
    }
)

print("write test code for READ_ONLY_KEY: ",r.status_code)
print(r.text)


# --------------------------------------------------
# 1. healthz
# --------------------------------------------------

r = requests.get(
    f"{BASE}/healthz",
    timeout=10,
)
show("1. healthz - expected 200", r)


# --------------------------------------------------
# 2. models without credential
# --------------------------------------------------

r = requests.get(
    f"{BASE}/v1/models",
    timeout=10,
)
show("2. models without key - expected 401", r)


# --------------------------------------------------
# 3. models with invalid credential
# --------------------------------------------------

r = requests.get(
    f"{BASE}/v1/models",
    headers={
        "Authorization": "Bearer sra_sk_invalid_key"
    },
    timeout=10,
)
show("3. models with invalid key - expected 401", r)


# --------------------------------------------------
# 4. models with OpenWebUI service key
# --------------------------------------------------

headers = {
    "Authorization": f"Bearer {OPENWEBUI_KEY}"
}

r = requests.get(
    f"{BASE}/v1/models",
    headers=headers,
    timeout=10,
)
show("4. models with valid key - expected 200", r)


# --------------------------------------------------
# 5. OpenWebUI key attempts report-job API
#
# If this key only has:
# model:read
# model:invoke
#
# expected = 403
# --------------------------------------------------

r = requests.post(
    f"{BASE}/v1/report/jobs",
    headers={
        **headers,
        "Content-Type": "application/json",
    },
    json={
        "prompt": "Phase 0 scope isolation test"
    },
    timeout=10,
)
show("5. report job using OpenWebUI key - expected 403", r)


# --------------------------------------------------
# 6. Actual OpenAI-compatible chat
# --------------------------------------------------
'''
r = requests.post(
    f"{BASE}/v1/chat/completions",
    headers={
        **headers,
        "Content-Type": "application/json",
        "X-OpenWebUI-Chat-Id": "python-phase0-test-001",
    },
    json={
        "model": "SRA-Structured Retrieval Agent",
        "messages": [
            {
                "role": "user",
                "content": "去年加薩衝突持續造成重大平民傷亡與人道危機，停火談判、人質釋放及人道援助准入逐漸形成彼此連動的重要議題。10月間哈馬斯表示準備釋放人質並展開對話，聯合國秘書長古特雷斯對此表示歡迎，卡達與埃及亦持續參與調解；同時聯合國已備妥大批食品、藥品及帳篷等物資，但軍事行動、邊境准入、安全通行及醫療系統惡化仍限制援助落實。請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊。**政治外交部門**掌握以色列、哈馬斯、美國、卡達、埃及及其他調解方之停火方案、人質交換條件與談判進展；**國際安全部門**追蹤空襲、地面軍事行動、停火違規及對平民與救援人員造成之安全影響；**人道事務部門**掌握食品、藥品、飲水、避難、邊境口岸與援助物資進入情形；**醫療衛生部門**追蹤醫院運作、醫療物資短缺、病患轉送及醫護人員安全；**國際組織部門**蒐集聯合國、人道協調廳、世衛組織及相關機構之聲明、數據與行動；**綜合研析部門**整合上述資訊，分析停火與人質談判是否實際改善人道准入與平民處境，辨識外交進展、軍事行動與人道情勢間之傳導關係，並提出談判破裂、援助受阻、醫療體系惡化及衝突再升級等後續風險。",
            }
        ],
        "stream": False,
    },
    timeout=(10, 1800)
)
'''
prompt = "請簡短回答測試訊息即可。"
prompt = "去年加薩衝突持續造成重大平民傷亡與人道危機，停火談判、人質釋放及人道援助准入逐漸形成彼此連動的重要議題。10月間哈馬斯表示準備釋放人質並展開對話，聯合國秘書長古特雷斯對此表示歡迎，卡達與埃及亦持續參與調解；同時聯合國已備妥大批食品、藥品及帳篷等物資，但軍事行動、邊境准入、安全通行及醫療系統惡化仍限制援助落實。請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊。**政治外交部門**掌握以色列、哈馬斯、美國、卡達、埃及及其他調解方之停火方案、人質交換條件與談判進展；**國際安全部門**追蹤空襲、地面軍事行動、停火違規及對平民與救援人員造成之安全影響；**人道事務部門**掌握食品、藥品、飲水、避難、邊境口岸與援助物資進入情形；**醫療衛生部門**追蹤醫院運作、醫療物資短缺、病患轉送及醫護人員安全；**國際組織部門**蒐集聯合國、人道協調廳、世衛組織及相關機構之聲明、數據與行動；**綜合研析部門**整合上述資訊，分析停火與人質談判是否實際改善人道准入與平民處境，辨識外交進展、軍事行動與人道情勢間之傳導關係，並提出談判破裂、援助受阻、醫療體系惡化及衝突再升級等後續風險。"

OUTPUT_DIR = r"D:\shared\topicclassification\poc-agent\tests_code\output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

try:
    r = requests.post(
        f"{BASE}/v1/chat/completions",
        headers={
            **headers,
            "Content-Type": "application/json",
            "X-OpenWebUI-Chat-Id": "python-phase0-test-001",
        },
        json={
            "model": "SRA-Structured Retrieval Agent",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": False,
        },
        timeout=(10, 1800),
    )

    show(
        "6. actual chat - expected 200 if backend is healthy",
        r,
    )

    if r.status_code == 200:
        data = r.json()

        # Phase 0 real E2E routing / retrieval evidence.
        # Do not treat HTTP 200 alone as sufficient: confirm the request
        # reached the expected report/analysis route and returned citations.
        message = data.get("choices", [{}])[0].get("message", {})
        context = message.get("context") or {}

        print()
        print("=== ROUTING EVIDENCE ===")
        print("mode :", context.get("mode"))
        print("route:", context.get("route"))

        citations = context.get("citations") or []
        print()
        print("=== CITATIONS ===")
        print("citation count:", len(citations))

        word_export = context["word_export"]

        word_url = word_export["url"]

        print()
        print("Word export URL:")
        print(word_url)

        print()
        print("Downloading Word...")

        # 注意：
        # 這是 signed capability URL。
        # 不要附 OpenWebUI Authorization header。
        word_response = requests.get(
            word_url,
            timeout=(10, 300),
        )

        print("Word download HTTP:", word_response.status_code)

        if word_response.status_code == 200:
            output_file = os.path.join(
                OUTPUT_DIR,
                "phase0_test_report.docx"
            )

            with open(output_file, "wb") as f:
                f.write(word_response.content)

            print()
            print("Word downloaded:")
            print(output_file)

        else:
            print("Word download failed:")
            print(word_response.text[:1000])

except requests.exceptions.ReadTimeout:
    print()
    print("=" * 70)
    print("6. actual chat")
    print("TIMEOUT: API 在設定時間內未完成")

except Exception as e:
    print()
    print("=" * 70)
    print("6. actual chat")
    print("ERROR:", repr(e))



#============sync key

r = requests.post(
    f"{BASE}/v1/report/word",
    headers={
        "Authorization": f"Bearer {REPORT_KEY}",
        "Content-Type": "application/json",
        "X-Session-Id": "python-report-test-001",
    },
    json={
        "model": "SRA-Structured Retrieval Agent",
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "stream": False,
        "filename": "gaza_report.docx",
    },
    timeout=(10, 1800),
)

print("HTTP:", r.status_code)
print("Content-Type:", r.headers.get("Content-Type"))

if r.status_code == 200:
    with open("gaza_report.docx", "wb") as f:
        f.write(r.content)

    print("Word saved: gaza_report.docx")
else:
    print(r.text)

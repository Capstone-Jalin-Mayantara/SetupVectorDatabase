"""
Test script: Pollinations.ai image generation (authenticated)
Jalankan: python test_pollinations_image.py
"""
import os, http.client, urllib.parse, subprocess
from dotenv import load_dotenv

load_dotenv()

POLL_TOKEN = os.getenv("POLLINATIONS_TOKEN", "")

def generate_image(prompt: str, output_path: str = "test_pollinations_output.jpg"):
    encoded = urllib.parse.quote(prompt)
    path = (
        f"/image/{encoded}"
        f"?model=flux&width=768&height=512&seed=-1&nologo=true"
    )

    headers = {
        "User-Agent": "ASIQ-PDF/1.0",
        "Authorization": f"Bearer {POLL_TOKEN}",
    }

    print(f"Token: {POLL_TOKEN[:10]}...")
    print(f"Connecting to gen.pollinations.ai...")

    conn = http.client.HTTPSConnection("gen.pollinations.ai", timeout=60)
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()

    print(f"Status: {resp.status} {resp.reason}")
    content_type = resp.getheader("Content-Type", "")
    data = resp.read()
    conn.close()

    if resp.status != 200:
        print(f"ERROR: {data[:300].decode('utf-8', errors='replace')}")
        return

    print(f"Response: {content_type}, {len(data):,} bytes")

    with open(output_path, "wb") as f:
        f.write(data)

    print(f"Gambar disimpan: {output_path}")
    subprocess.Popen(["explorer", output_path])
    print("SUKSES!")

generate_image(
    "Simple flat illustration of an elementary school student "
    "happily learning mathematics with books and numbers. "
    "Colorful, child-friendly, white background, vector style."
)

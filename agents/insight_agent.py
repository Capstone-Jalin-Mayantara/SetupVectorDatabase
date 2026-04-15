from llm_config import generate_response

def inclusivity_insight(materi):
    prompt = f"""
    Evaluasi materi berikut dari sisi inklusivitas pembelajaran.

    Materi:
    {materi}

    Berikan:
    1. Skor inklusivitas (1-100)
    2. Kelebihan
    3. Rekomendasi perbaikan
    """
    return generate_response(prompt)
from llm_config import generate_response

def adaptive_transformation(materi, profil):
    prompt = f"""
    Sesuaikan materi berikut agar sesuai dengan profil siswa.

    Materi:
    {materi}

    Profil siswa:
    {profil}

    Buat lebih sederhana, jelas, dan mudah dipahami.
    """
    return generate_response(prompt)
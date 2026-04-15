from llm_config import generate_response

def learner_profiling(input_data):
    prompt = f"""
    Analisis karakteristik siswa berikut:
    {input_data}

    Jelaskan:
    - Gaya belajar
    - Kesulitan utama
    - Kebutuhan khusus
    """

    return generate_response(prompt)
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings

def get_vector_db():
    embedding = OpenAIEmbeddings()

    db = Chroma(
        collection_name="education_rag",
        embedding_function=embedding,
        persist_directory="./chroma_db"
    )
    return db
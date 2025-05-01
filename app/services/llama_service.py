import subprocess
from app.config.settings import LLAMA_CPP_PATH, MODEL_PATH


class LlamaService:

    def __init__(self):
        self.llama_cpp = LLAMA_CPP_PATH
        self.llama_model = MODEL_PATH

    def generate_response(self, prompt: str):
        command = [
            self.llama_cpp,
            "-m", self.llama_model,
            "-n", "200",
            "-ngl", "0",
            prompt
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        return result.stdout


llama_service = LlamaService()

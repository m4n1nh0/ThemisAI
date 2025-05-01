# FastAPI LLaMA API

Este projeto é uma API baseada no FastAPI que integra o modelo de linguagem LLaMA para geração de respostas e treinamento, armazenando e consultando dados no OpenSearch.

## Definição do projeto

O projeto que você está desenvolvendo utiliza uma arquitetura modular, baseada na divisão de responsabilidades entre diferentes componentes. Vou te explicar cada parte e como ela se integra no processo de utilização da LLaMA para gerar respostas com base nos resultados da busca no OpenSearch. A estrutura geral do projeto segue o padrão de desenvolvimento de APIs, com foco na escalabilidade e organização.

Arquitetura e Fluxo
A arquitetura do projeto segue um padrão de microserviços para um backend em FastAPI. A principal responsabilidade é receber as consultas dos usuários, buscar os dados no OpenSearch, e utilizar a LLaMA (um modelo de linguagem) para gerar respostas, com base nesses dados.

### FastAPI como Framework Principal:

O FastAPI é utilizado como o framework principal para criar a API. Ele gerencia as requisições HTTP, validações e responde ao usuário com as informações geradas pelo modelo LLaMA.

### Divisão em Módulos:

O projeto segue a arquitetura de módulos, onde cada módulo tem uma responsabilidade específica. A estrutura está dividida em várias pastas (como models, services, routes, etc.) para separar as responsabilidades e facilitar a manutenção.

### Busca no OpenSearch:

O serviço de opensearch_service.py é responsável por interagir com o OpenSearch. Quando o usuário faz uma consulta, esse serviço se comunica com o OpenSearch para buscar os dados relevantes.

### Geração de Respostas com LLaMA:

A LLaMA é usada dentro do llama_service.py para gerar respostas contextuais. O modelo recebe como entrada o conteúdo dos resultados da busca no OpenSearch e gera uma resposta personalizada, de forma eficiente.

### Autenticação e Autorização:

A parte de auth.py cuida da autenticação dos usuários. Esse módulo é responsável por garantir que as requisições sejam feitas de maneira segura e autorizada.

## Fluxo Completo
O usuário faz uma requisição para a API (por exemplo, através de um endpoint como /ask).

A requisição chega ao ask.py, onde é tratada.

O ask.py chama o opensearch_service.py para realizar a busca no OpenSearch.

Os resultados da busca são passados para o llama_service.py, que utiliza a LLaMA para gerar uma resposta mais personalizada e contextual.

A resposta gerada é retornada ao usuário.

## 📂 Estrutura do Projeto

```
fastapi-llama-api/
│── app/
│   ├── config/                  # Configurações gerais
│   │   ├── __init__.py
│   ├── db/                      # Gerenciamento do banco de dados
│   │   ├── __init__.py
│   ├── models/                   # Modelos de dados
│   │   ├── __init__.py
│   ├── routes/                   # Rotas da API
│   │   ├── __init__.py
│   │   ├── auth.py               # Autenticação
│   │   ├── training.py           # Treinamento do modelo
│   │   ├── ask.py                # Geração de respostas
│   ├── services/                 # Serviços internos
│   │   ├── __init__.py
│   │   ├── opensearch_service.py # Conexão com OpenSearch
│   │   ├── llama_service.py      # Interação com LLaMA
│   ├── __init__.py
│   ├── main.py                   # Ponto de entrada da API
│── requirements.txt              # Dependências do projeto
│── Dockerfile                    # Configuração do Docker
│── docker-compose.yml            # Orquestração de containers
```

## 🚀 Configuração e Execução

### Pré-requisitos
- Python 3.10+
- Docker e Docker Compose (caso queira rodar via containers)
- OpenSearch em execução
- Modelo LLaMA disponível

### 1️⃣ Configuração do Ambiente Virtual
```sh
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate  # Windows
```

### 2️⃣ Instalação das Dependências
```sh
pip install -r requirements.txt
```

### 3️⃣ Execução da API
```sh
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4️⃣ Execução com Docker
```sh
docker-compose up --build
```

## 🛠️ Endpoints Principais

### 🔑 Autenticação (`/auth`)
- `POST /auth/login` → Gera um token de autenticação.

### 📚 Treinamento (`/training`)
- `POST /training/train` → Treina o modelo com novos dados.

### 🤖 Geração de Respostas (`/ask`)
- `POST /ask/question` → Retorna uma resposta baseada no modelo LLaMA.

## 🏗️ Tecnologias Utilizadas
- **FastAPI** → Backend
- **LLaMA** → Modelo de linguagem
- **OpenSearch** → Armazenamento e indexação
- **Docker** → Containerização

## 📌 Contribuição
Se deseja contribuir, faça um fork do projeto e crie um pull request com suas melhorias!

## 📝 Licença
Este projeto segue a licença MIT.


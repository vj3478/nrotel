FROM python:3.10-slim
WORKDIR /app
RUN pip install pipenv
COPY Pipfile .
COPY Pipfile.lock .
RUN pipenv install --deploy --ignore-pipfile
COPY src/ ./src/
COPY templates/ ./templates/
CMD ["pipenv", "run", "python", "src/main.py"]
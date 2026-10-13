# Two targets from one codebase:
#   docker build --target lambda -t uif-lambda .   -> light steps (intake, guard, classify, resolve, validate, publish)
#   docker build --target task   -t uif-task   .   -> heavy steps on ECS Fargate (normalize, extract)

FROM public.ecr.aws/lambda/python:3.12 AS lambda
COPY pyproject.toml ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src
COPY config ${LAMBDA_TASK_ROOT}/config
COPY registry ${LAMBDA_TASK_ROOT}/registry
COPY sql ${LAMBDA_TASK_ROOT}/sql
COPY data ${LAMBDA_TASK_ROOT}/data
RUN pip install --no-cache-dir "${LAMBDA_TASK_ROOT}[aws]"
ENV RUNTIME=aws UIF_HOME=${LAMBDA_TASK_ROOT}
CMD ["uif.aws_handler.handler"]

FROM python:3.12-slim AS task
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
COPY registry ./registry
COPY sql ./sql
COPY data ./data
RUN pip install --no-cache-dir ".[aws]"
ENV RUNTIME=aws UIF_HOME=/app
# Step Functions overrides the command per step, e.g. ["python","-m","uif.cli","step","extract"] with DOC_ID set.
CMD ["python", "-m", "uif.cli", "--help"]

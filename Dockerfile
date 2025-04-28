FROM python:3.12 as requirements_stage

WORKDIR /wheel

RUN python -m pip install --user pipx

COPY ./pyproject.toml \
  ./requirements.txt \
  /wheel/


RUN python -m pip wheel --wheel-dir=/wheel --no-cache-dir --requirement ./requirements.txt

RUN python -m pipx run --no-cache nb-cli generate -f /tmp/bot.py


FROM python:3.12-slim

WORKDIR /app

ENV TZ Asia/Shanghai
ENV PYTHONPATH=/app
ENV ALEMBIC_STARTUP_CHECK false
ENV ENVIRONMENT dev
ENV SQLALCHEMY_DATABASE_URL sqlite+aiosqlite:///./data/db.sqlite3
ENV PYTHON_VERSION 3.12.10
ENV HOST: 0.0.0.0
ENV PORT: 12035

COPY ./docker/gunicorn_conf.py ./docker/start.sh /
RUN chmod +x /start.sh

ENV APP_MODULE _main:app
ENV MAX_WORKERS 1



COPY --from=requirements_stage /tmp/bot.py /app
COPY ./docker/_main.py /app
COPY --from=requirements_stage /wheel /wheel

RUN pip install --no-cache-dir gunicorn uvicorn[standard] nonebot2 \
  && pip install --no-cache-dir --no-index --force-reinstall --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel
COPY . /app/

CMD ["/start.sh"]
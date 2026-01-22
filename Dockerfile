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

COPY ./docker/gunicorn_conf.py ./docker/start.sh ./docker/prestart.sh /app/
RUN chmod +x /app/start.sh /app/prestart.sh

ENV APP_MODULE _main:app
ENV MAX_WORKERS 1

COPY --from=requirements_stage /tmp/bot.py /app
COPY ./docker/_main.py /app
COPY --from=requirements_stage /wheel /wheel

RUN pip install --no-cache-dir gunicorn uvicorn[standard] nonebot2 nb-cli \
  && pip install --no-cache-dir --no-index --force-reinstall --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel
COPY . /app/

CMD ["/app/start.sh"]
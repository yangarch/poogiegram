.DEFAULT_GOAL := help
SHELL := /bin/bash

# /dev/dri 가 있으면 VA-API 오버레이를 함께 적용한다 (§6.4).
COMPOSE_FILES := -f docker-compose.yml
ifneq ($(wildcard /dev/dri),)
COMPOSE_FILES += -f docker-compose.vaapi.yml
endif
DC := docker compose $(COMPOSE_FILES)

help: ## 사용 가능한 명령
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## 전체 스택 기동 (헬스체크 통과까지 대기)
	$(DC) up -d --build --wait
	@echo
	@$(MAKE) --no-print-directory status

down: ## 전체 스택 정지
	$(DC) down

logs: ## 로그 추적 (S=서비스명 으로 한정 가능)
	$(DC) logs -f $(S)

ps: ## 컨테이너 상태
	$(DC) ps

status: ## 헬스체크 확인
	@$(DC) ps
	@echo
	@port=$${API_PORT:-8005}; \
	for i in $$(seq 1 15); do \
		if out=$$(curl -fsS --max-time 3 http://127.0.0.1:$$port/readyz 2>/dev/null); then \
			echo "$$out"; exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "readyz 실패 (30초 대기 후) — 원인 확인:"; \
	echo "  make logs S=api"; \
	curl -sS --max-time 3 http://127.0.0.1:$$port/readyz || true; \
	exit 1

shell: ## api 컨테이너 셸
	$(DC) exec api bash

psql: ## DB 접속
	$(DC) exec db psql -U $${POSTGRES_USER:-poogiegram} -d $${POSTGRES_DB:-poogiegram}

vainfo: ## 워커 컨테이너에서 VA-API 확인 (§6.4)
	$(DC) exec worker vainfo --display drm --device /dev/dri/renderD128

dump: ## pg_dump → $(MEDIA_ROOT)/db/ (§4.2)
	$(DC) exec -T db pg_dump -Fc -U $${POSTGRES_USER:-poogiegram} $${POSTGRES_DB:-poogiegram} \
		> $${MEDIA_ROOT:-/mnt/media}/db/$$(date +%F-%H%M).dump
	@echo "덤프 완료: $${MEDIA_ROOT:-/mnt/media}/db/"

.PHONY: help up down logs ps status shell psql vainfo dump

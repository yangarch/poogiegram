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

up: ## 전체 스택 기동 — 마이그레이션까지 적용하고 상태를 확인한다
	@$(MAKE) --no-print-directory check-gid
	$(DC) up -d --build --wait
	@echo "마이그레이션 적용..."
	@$(DC) exec -T api alembic upgrade head
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

check-gid: ## .env 의 GID 가 호스트 그룹과 맞는지 확인
	@set -e; \
	. ./.env 2>/dev/null || { echo ".env 가 없습니다. cp .env.example .env"; exit 1; }; \
	command -v getent >/dev/null || { echo "getent 없음 — GID 확인을 건너뜁니다(리눅스 호스트가 아님)"; exit 0; }; \
	real_pg=$$(getent group poogiegram | cut -d: -f3); \
	real_rd=$$(getent group render     | cut -d: -f3); \
	[ -n "$$real_pg" ] || { echo "poogiegram 그룹이 없습니다:  sudo groupadd -f poogiegram"; exit 1; }; \
	[ "$$POOGIEGRAM_GID" = "$$real_pg" ] || { \
		echo "POOGIEGRAM_GID 불일치: .env=$$POOGIEGRAM_GID, 실제=$$real_pg"; \
		echo "  sed -i 's/^POOGIEGRAM_GID=.*/POOGIEGRAM_GID=$$real_pg/' .env"; exit 1; }; \
	if [ -e /dev/dri ]; then \
		[ -n "$$real_rd" ] || { echo "render 그룹이 없습니다. /dev/dri 소유 그룹을 확인하세요:"; \
			stat -c '  %n → 그룹 %G (gid %g)' /dev/dri/renderD128; exit 1; }; \
		[ "$$RENDER_GID" = "$$real_rd" ] || { \
			echo "RENDER_GID 불일치: .env=$$RENDER_GID, 실제=$$real_rd"; \
			echo "  sed -i 's/^RENDER_GID=.*/RENDER_GID=$$real_rd/' .env"; exit 1; }; \
		[ "$$RENDER_GID" != "$$POOGIEGRAM_GID" ] || { \
			echo "RENDER_GID 와 POOGIEGRAM_GID 가 같습니다($$RENDER_GID). 서로 다른 그룹이므로 한쪽이 잘못됐습니다."; \
			getent group render poogiegram; exit 1; }; \
	fi; \
	echo "GID 확인: poogiegram=$$POOGIEGRAM_GID render=$${RENDER_GID:-(GPU 없음)}"

retry-derive: ## 실패한 파생물을 다시 시도 (원인을 고친 뒤 실행)
	$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d $${POSTGRES_DB:-poogiegram} \
		-c "UPDATE asset SET derive_status='pending' WHERE derive_status='failed' AND deleted_at IS NULL;"
	@# arq 가 보관 중인 이전 결과를 지운다. 남아 있으면 같은 job_id 의 재큐잉이 무시된다.
	@$(DC) exec -T redis sh -c "redis-cli --scan --pattern 'arq:result:derive:*' | xargs -r redis-cli del" >/dev/null 2>&1 || true
	@curl -sXPOST http://127.0.0.1:$${API_PORT:-8005}/api/ingest/scan >/dev/null && echo "재시도 큐잉됨"

status-derive: ## 파생물 상태 요약
	@$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d $${POSTGRES_DB:-poogiegram} -tAc \
		"SELECT derive_status, count(*) FROM asset WHERE deleted_at IS NULL GROUP BY derive_status ORDER BY 1;"

create-user: ## 계정 생성 (E=이메일, ADMIN=1 이면 관리자)
	@test -n "$(E)" || { echo 'E=이메일 을 지정하세요. 예: make create-user E=me@example.com ADMIN=1'; exit 1; }
	$(DC) exec api python -m poogiegram.cli create-user "$(E)" $(if $(ADMIN),--admin,) $(if $(NAME),--name "$(NAME)",)

users: ## 계정 목록
	@$(DC) exec -T api python -m poogiegram.cli list-users

passwd: ## 비밀번호 변경 (E=이메일)
	@test -n "$(E)" || { echo 'E=이메일 을 지정하세요'; exit 1; }
	$(DC) exec api python -m poogiegram.cli passwd "$(E)"

migrate: ## DB 마이그레이션 적용
	$(DC) exec api alembic upgrade head
	@echo
	@$(MAKE) --no-print-directory status

migration: ## 새 마이그레이션 생성 (M="설명")
	@test -n "$(M)" || { echo 'M="설명" 을 지정하세요. 예: make migration M="add caption"'; exit 1; }
	$(DC) exec api alembic revision --autogenerate -m "$(M)"
	@echo "생성된 파일을 반드시 눈으로 확인하세요 — autogenerate 가 놓치는 것이 있습니다"

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

.PHONY: help up down logs ps status check-gid retry-derive status-derive create-user users passwd migrate migration shell psql vainfo dump

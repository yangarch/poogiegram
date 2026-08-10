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

logs: ## 로그 추적 — Ctrl+C 로 종료 (S=서비스명 으로 한정 가능)
	$(DC) logs -f $(S)

tail: ## 최근 로그만 출력하고 끝낸다 (S=서비스명, N=줄수, 기본 40)
	@$(DC) logs --tail=$(if $(N),$(N),40) $(S)

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

fix-perms: ## 파생물 권한을 그룹 읽기 가능하게 되돌린다 (nginx 가 못 읽을 때)
	@# g+s 로 setgid 를 되살린다. 이게 없으면 새로 만드는 파일이 poogiegram 이 아니라
	@# 컨테이너 주 그룹(app)으로 생겨서, 권한을 고쳐도 다음 파생물부터 다시 안 보인다.
	sudo find $${DERIVED_ROOT:-/var/lib/poogiegram/derived} -type d -exec chmod g+rxs {} +
	sudo find $${DERIVED_ROOT:-/var/lib/poogiegram/derived} -type f -exec chmod g+r {} +
	sudo chgrp -R $${POOGIEGRAM_GROUP:-poogiegram} $${DERIVED_ROOT:-/var/lib/poogiegram/derived}
	@echo "완료. nginx 를 재시작하면 반영됩니다:  sudo systemctl restart nginx"

test: ## 테스트 실행 (K=키워드 로 한정 가능). DB 테스트는 건너뛴다
	@# 운영 이미지에는 tests/ 도 pytest 도 넣지 않는다 (Dockerfile 은 앱만 COPY).
	@# 소스를 마운트하고 테스트 의존성은 임시 컨테이너 안에서만 설치한다.
	@#
	@# **DATABASE_URL 을 비우는 것이 핵심이다.** 앱 컨테이너에서 돌므로 그냥 두면
	@# 운영 DB 를 물려받는데, DB 테스트는 asset 테이블을 통째로 비운다.
	@# 실제로 이걸 빠뜨려 사진 행이 전부 지워졌다. DB 테스트는 make test-db 로.
	$(DC) run --rm --no-deps -T -e DATABASE_URL= -v "$(CURDIR)/backend:/src" -w /src api sh -c \
		"pip install -q --user -r requirements-dev.txt && python -m pytest -q -o cache_dir=/tmp/pytest_cache $(if $(K),-k '$(K)',)"

test-db: ## DB 가 필요한 테스트까지 실행 (전용 테스트 DB 를 새로 만든다)
	@set -e; \
	run() { $(DC) run --rm --no-deps -T -v "$(CURDIR)/backend:/src" -w /src api "$$@"; }; \
	name=$$(run python tests/testdb.py --name | tr -d '\r'); \
	echo "테스트 DB: $$name (운영 DB 는 건드리지 않습니다)"; \
	$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d postgres -c "DROP DATABASE IF EXISTS $$name" >/dev/null; \
	$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d postgres -c "CREATE DATABASE $$name" >/dev/null; \
	run sh -c 'export DATABASE_URL=$$(python tests/testdb.py) \
		&& pip install -q --user -r requirements-dev.txt \
		&& alembic upgrade head >/dev/null \
		&& python -m pytest -q -o cache_dir=/tmp/pytest_cache'

reindex: ## originals/ 를 훑어 DB 에 없는 파일을 등록한다 (DB 만 잃었을 때 복구)
	$(DC) exec -T api python -m poogiegram.cli reindex

retry-derive: ## 실패한 파생물을 다시 시도 (원인을 고친 뒤 실행)
	$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d $${POSTGRES_DB:-poogiegram} \
		-c "UPDATE asset SET derive_status='pending' WHERE derive_status='failed' AND deleted_at IS NULL;"
	@# arq 가 보관 중인 이전 결과를 지운다. 남아 있으면 같은 job_id 의 재큐잉이 무시된다.
	@$(DC) exec -T redis sh -c "redis-cli --scan --pattern 'arq:result:derive:*' | xargs -r redis-cli del" >/dev/null 2>&1 || true
	@curl -sXPOST http://127.0.0.1:$${API_PORT:-8005}/api/ingest/scan >/dev/null && echo "재시도 큐잉됨"

status-derive: ## 파생물 상태 요약 (실패 사유 포함)
	@$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d $${POSTGRES_DB:-poogiegram} -tAc \
		"SELECT derive_status, count(*) FROM asset WHERE deleted_at IS NULL GROUP BY derive_status ORDER BY 1;"
	@# 실패 사유를 바로 보여준다. 이게 없어서 로그를 뒤져야 했다.
	@$(DC) exec -T db psql -U $${POSTGRES_USER:-poogiegram} -d $${POSTGRES_DB:-poogiegram} -qAF'  ' \
		-c "SELECT original_filename, left(derive_error, 90) FROM asset \
		    WHERE derive_status = 'failed' AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10;" \
		| sed '/^$$/d;$$d'

create-user: ## 계정 생성 (U=아이디, NAME=표시이름, ADMIN=1 이면 관리자)
	@test -n "$(U)" || { echo 'U=아이디 를 지정하세요. 예: make create-user U=kiseok NAME="기석" ADMIN=1'; exit 1; }
	$(DC) exec api python -m poogiegram.cli create-user "$(U)" $(if $(ADMIN),--admin,) $(if $(NAME),--name "$(NAME)",)

users: ## 계정 목록
	@$(DC) exec -T api python -m poogiegram.cli list-users

passwd: ## 비밀번호 변경 (U=아이디)
	@test -n "$(U)" || { echo 'U=아이디 를 지정하세요'; exit 1; }
	$(DC) exec api python -m poogiegram.cli passwd "$(U)"

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

.PHONY: help up down logs tail ps status check-gid fix-perms test test-db reindex retry-derive status-derive create-user users passwd migrate migration shell psql vainfo dump

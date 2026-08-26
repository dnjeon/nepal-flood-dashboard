# 네팔 홍수·산사태 실시간 뉴스 대시보드

라수와(Rasuwa)·보테코시(Bhotekoshi) 돌발 홍수 관련 뉴스를 네팔 현지 + 한국 소스에서
자동 수집해 보여주는 공개 대시보드입니다. 두산에너빌리티/한국인 관련 기사를 우선 강조합니다.

## 구조
- `scripts/collect.py` — RSS 수집 + 키워드 필터 → `docs/data/data.json` 생성 (Python 표준 라이브러리만 사용)
- `docs/index.html` — 단일 파일 대시보드 (의존성 없음), 60초마다 자동 새로고침
- `.github/workflows/deploy.yml` — 10분마다 수집 후 커밋 + GitHub Pages 배포

## 로컬 실행
```bash
python3 scripts/collect.py
cd docs && python3 -m http.server 8777
# http://localhost:8777
```

## 소스
현지: The Kathmandu Post, Online Khabar, The Rising Nepal · 한국: 연합뉴스(EN/KR) · 국제: Al Jazeera

## 주의
공개 뉴스 피드 자동 집계이며, 실종자 공식 확인은 외교부 영사콜센터(+82-2-3210-0404) 및
주네팔 대한민국 대사관을 통해 진행하세요.

# Quant Trading Bot

암호화폐 퀀트 백테스트 실험실. (배경·로드맵: [`PLAN.md`](PLAN.md), 설계: [`docs/design/`](docs/design/))

> 요구사항: Python 3.13 (권장). venv는 `python3.13`로 생성.

## 설치

```bash
python3.13 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt   # `pip` 대신 `python -m pip` (활성화된 venv에 정확히 설치)
```

## 1. 데이터 받기

`data/`는 저장소에 포함되지 않으므로 먼저 받아야 한다.

```bash
python fetch.py                  # BTC/USDT 1h·4h 약 3년치 → data/ 생성 (인터넷 필요)
```

## 2. 백테스트 실행

```bash
python backtest.py               # SMA 교차 전략 백테스트 → 수익률·샤프·MDD·거래수 출력
```

## 3. 테스트

```bash
python -m pytest -q              # 7 passed
```

## 4. 노트북 (선택)

```bash
jupyter notebook research/2026-06-25_hello_world.ipynb
```

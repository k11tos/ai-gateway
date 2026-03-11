# AI Gateway

## Install

Runtime dependencies are intentionally minimized in `requirements.txt`.

```bash
pip install -r requirements.txt
```


## API

- `GET /health`: FastAPI 프로세스뿐 아니라 Ollama upstream 연결 상태까지 확인하며, upstream 장애 시 `503`을 반환
- `POST /chat`: 기본 텍스트 생성 엔드포인트
- `POST /generate`: `POST /chat`와 동일 동작(하위 호환용, deprecated)

신규 클라이언트는 `POST /chat` 사용을 권장합니다.

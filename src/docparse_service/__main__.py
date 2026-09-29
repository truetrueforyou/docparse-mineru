import uvicorn


def main() -> None:
    # app.py is added in a later task; string import defers loading until runtime.
    uvicorn.run("docparse_service.app:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

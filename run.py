import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Launch BICE with optional N-BaIoT dataset folder.")
    parser.add_argument("--dataset", help="Path to N-BaIoT dataset folder or single CSV file")
    parser.add_argument("--port", default="8000", help="Port for the FastAPI server")
    args = parser.parse_args()

    dataset_path = args.dataset or os.getenv("BICE_DATASET_PATH")
    if not dataset_path:
        if sys.stdin.isatty():
            dataset_path = input("Enter the N-BaIoT dataset folder or CSV file path (leave empty for synthetic simulation): ").strip()
        else:
            dataset_path = sys.stdin.read().strip()

    if dataset_path:
        if not os.path.exists(dataset_path):
            print(f"Error: dataset path does not exist: {dataset_path}")
            sys.exit(1)
        os.environ["BICE_DATASET_PATH"] = os.path.abspath(dataset_path)

    os.environ.setdefault("BICE_DATASET_NAME", "n_baiot")

    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", args.port])


if __name__ == "__main__":
    main()

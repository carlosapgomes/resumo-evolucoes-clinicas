import argparse
import os

from aghu import capture_evolution_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa a captura do texto das evoluções no AGHUse para um registro de paciente."
    )
    parser.add_argument(
        "patient_record",
        nargs="?",
        default=os.getenv("PATIENT_REC_NUMBER"),
        help="Registro do paciente. Se omitido, usa PATIENT_REC_NUMBER do ambiente.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    patient_record = (args.patient_record or "").strip()

    if not patient_record:
        raise SystemExit(
            "Informe o registro do paciente via argumento ou defina PATIENT_REC_NUMBER no .env."
        )

    text = capture_evolution_text(patient_record)
    print("\n=== Texto capturado ===\n")
    print(text)


if __name__ == "__main__":
    main()

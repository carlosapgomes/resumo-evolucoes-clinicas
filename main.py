import argparse
import os
from datetime import date, timedelta

from aghu import capture_evolution_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa a captura das evoluções por intervalo de datas no AGHUse para um registro de paciente."
    )
    parser.add_argument(
        "patient_record",
        nargs="?",
        default=os.getenv("PATIENT_REC_NUMBER"),
        help="Registro do paciente. Se omitido, usa PATIENT_REC_NUMBER do ambiente.",
    )
    parser.add_argument(
        "--start-date",
        default=_default_start_date(),
        help="Data inicial no formato YYYY-MM-DD. Padrão: há 5 dias.",
    )
    parser.add_argument(
        "--end-date",
        default=_default_end_date(),
        help="Data final no formato YYYY-MM-DD. Padrão: hoje.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    patient_record = (args.patient_record or "").strip()

    if not patient_record:
        raise SystemExit(
            "Informe o registro do paciente via argumento ou defina PATIENT_REC_NUMBER no .env."
        )

    interval_start_datetime = _iso_to_aghu_datetime(args.start_date, suffix="00:01")
    interval_end_datetime = _iso_to_aghu_datetime(args.end_date, suffix="23:59")

    result = capture_evolution_data(
        patient_record,
        interval_start_datetime,
        interval_end_datetime,
    )

    if result.patient_summary:
        print("\n=== Resumo do paciente ===\n")
        print(result.patient_summary)

    print("\n=== Texto capturado e ordenado ===\n")
    print(result.raw_text)


def _default_start_date() -> str:
    return (date.today() - timedelta(days=5)).isoformat()


def _default_end_date() -> str:
    return date.today().isoformat()


def _iso_to_aghu_datetime(value: str, *, suffix: str) -> str:
    parsed = date.fromisoformat(value)
    return parsed.strftime("%d/%m/%Y") + f" {suffix}"


if __name__ == "__main__":
    main()

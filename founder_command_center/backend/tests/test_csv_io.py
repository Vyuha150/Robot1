from app.services.csv_io import export_csv


class Row:
    company_name = "Example Hospital"
    industry = "Hospital"


def test_export_csv_writes_headers_and_rows() -> None:
    csv_text = export_csv([Row()], ["company_name", "industry"])
    assert "company_name,industry" in csv_text
    assert "Example Hospital,Hospital" in csv_text

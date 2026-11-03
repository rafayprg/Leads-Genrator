import io

from openpyxl import load_workbook

from app.ingest.apify_maps import to_record
from app.ingest.records import save
from tests.fakes import place


def _seed(maker):
    with maker() as s:
        save(s, [to_record(place(), "AE", "Dubai", "beauty"),
                 to_record(place(title="=HYPERLINK(evil)", placeId="P2", phoneUnformatted="+97142220000",
                                 website="https://other.ae", location={"lat": 25.3, "lng": 55.4}), "AE", "Dubai", "beauty")])


def test_xlsx_export_has_all_leads(client, maker):
    _seed(maker)
    r = client.get("/businesses/export", params={"format": "xlsx", "country": "AE"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws.cell(1, 1).value == "Business ID" and ws.max_row == 3
    names = {ws.cell(i, 2).value: ws.cell(i, 2).data_type for i in (2, 3)}
    assert names["=HYPERLINK(evil)"] == "s"  # stored as text, not a formula


def test_csv_export_defuses_formulas_and_filters(client, maker):
    _seed(maker)
    text = client.get("/businesses/export", params={"format": "csv"}).content.decode("utf-8-sig")
    assert "'=HYPERLINK(evil)" in text and "Glow Ladies Salon" in text
    only = client.get("/businesses/export", params={"format": "csv", "q": "glow"}).content.decode("utf-8-sig")
    assert "HYPERLINK" not in only

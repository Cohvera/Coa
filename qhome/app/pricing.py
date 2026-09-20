from decimal import Decimal, ROUND_HALF_UP
from .importer import number, normalize, unit


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def match(lines, catalog):
    for line in lines:
        candidates = [c for c in catalog if c["active"] and unit(c["unit"]) == unit(line["unit"])
                      and normalize(line["match_text"]) in [normalize(c["name"]), *[normalize(a) for a in c["aliases"]]]]
        line["catalog_id"] = candidates[0]["id"] if len(candidates) == 1 else None
    return lines


def calculate(lines, settings, catalog):
    lookup = {c["id"]: c for c in catalog}
    discount = Decimal(number(settings.get("discount", "0")) or "0")
    vat = Decimal(number(settings.get("vat", "21")) or "0")
    fixed = money(number(settings.get("fixed", "0")) or "0")
    if discount > 100 or vat > 100:
        raise ValueError("Korting en btw moeten tussen 0 en 100 liggen.")
    errors, rows, subtotal = [], [], Decimal(0)
    for line in lines:
        row = dict(line)
        row.update(price=None, total=None, pricing_error="")
        if line.get("excluded"):
            if not str(line.get("reason", "")).strip():
                row["pricing_error"] = "Geef een reden voor uitsluiting."
        else:
            item = lookup.get(line.get("catalog_id"))
            try:
                qty = number(line.get("quantity"))
            except ValueError:
                qty = None
            if qty is None:
                row["pricing_error"] = "Hoeveelheid ontbreekt of is ongeldig."
            elif not line.get("unit"):
                row["pricing_error"] = "Eenheid ontbreekt."
            elif not item or not item["active"]:
                row["pricing_error"] = "Koppel een actieve prijspost."
            elif unit(item["unit"]) != unit(line["unit"]):
                row["pricing_error"] = "Eenheid wijkt af van de prijslijst."
            elif item["price"] is None:
                row["pricing_error"] = "Standaardprijs ontbreekt."
            else:
                row["price"] = str(money(item["price"]))
                row["total"] = str(money(Decimal(qty) * Decimal(row["price"])))
                row["catalog_name"] = item["name"]
                subtotal += Decimal(row["total"])
        if row["pricing_error"]:
            errors.append({"row": line["source_row"], "message": row["pricing_error"]})
        rows.append(row)
    if not any(not l.get("excluded") for l in lines):
        errors.append({"row": None, "message": "Neem minstens één post op in de offerte."})
    reduction = money(subtotal * discount / 100)
    net = subtotal - reduction + fixed
    tax = money(net * vat / 100)
    return {"lines": rows, "errors": errors, "ready": not errors,
            "subtotal": str(subtotal), "discount_amount": str(reduction), "fixed": str(fixed),
            "net": str(net), "vat_amount": str(tax), "gross": str(net + tax)}

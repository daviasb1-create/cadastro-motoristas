from services.textutil import (canonical_url, detect_ufs, find_cnpjs, find_emails, find_phones,
                               find_whatsapp_links, format_cnpj, is_corporate_email, no_dash,
                               normalize_name, valid_cnpj, whatsapp_number)


def test_cnpj_validation():
    assert valid_cnpj("11.222.333/0001-81")
    assert not valid_cnpj("11.222.333/0001-82")
    assert not valid_cnpj("00000000000000")
    assert find_cnpjs("CNPJ 11.222.333/0001-81 e 11.222.333/0001-99") == ["11222333000181"]
    assert format_cnpj("11222333000181") == "11.222.333/0001-81"


def test_emails_and_phones():
    text = "Fale com logistica@aurora.com.br ou (21) 99876-5432, fixo 21 3333-4444, img logo@2x.png"
    assert find_emails(text) == ["logistica@aurora.com.br"]
    assert "21998765432" in find_phones(text)
    assert "2133334444" in find_phones(text)
    assert is_corporate_email("compras@aurora.com.br", "aurora.com.br")
    assert not is_corporate_email("fulano@gmail.com")


def test_whatsapp():
    assert whatsapp_number("(21) 99876-5432") == "5521998765432"
    assert whatsapp_number("(21) 3333-4444") is None
    assert find_whatsapp_links('<a href="https://wa.me/5521998765432">') == ["5521998765432"]


def test_normalize_and_dedup_keys():
    assert normalize_name("Móveis Aurora LTDA") == normalize_name("MOVEIS AURORA S.A.")
    assert canonical_url("https://www.x.com/a/?utm_source=1&id=2") == canonical_url("https://x.com/a?id=2")


def test_detect_ufs():
    ufs = detect_ufs("Transferência entre Rio de Janeiro e Joinville")
    assert "RJ" in ufs and "SC" in ufs


def test_no_dash():
    assert "—" not in no_dash("Olá — tudo bem")


def test_route_only_when_declared():
    from services.textutil import detect_route
    assert detect_route("CD em Joinville para abastecer Rio de Janeiro e São Paulo") == (None, None)
    assert detect_route("cotação de frete de São Paulo para Joinville") == ("São Paulo", "Joinville")
    assert detect_route("rota RJ x SP") == ("RJ", "SP")
    assert "PA" not in detect_ufs("carga para abastecer a loja")

import pytest
from contentextraction.att_extractor import AttExtractor


@pytest.fixture()
def att_extractor():
    return AttExtractor({
        "Birgitte Andersen": "birgitte.andersen@gmail.com",
        "Tonni Bonde": "tonni.bonde@gmail.com",
        "Birgitte Hansen": "birgitte.hansen@gmail.com",
        "Birgitte Sørensen-Hansen": "birgitte.sørensen.hanse@gmail.com"
    })


@pytest.mark.parametrize("subject,body,expected_mail", [
    ("Att.: Birgitte Andersen - Angående min aftale.", "", "birgitte.andersen@gmail.com"),
    ("FW: Att: Tonni Bonde - Visitation og hjælpemiddelafdeling", "", "tonni.bonde@gmail.com"),
    ("Digitalpost (CVR: 29189): Brev Ældrebolig ansøgning - att. Birgitte Sørensen-Hansen (88888)", "",
     "birgitte.sørensen.hanse@gmail.com"),
    ("att birgitte andersen", "", "birgitte.andersen@gmail.com"),
    ("Emne", "Hej\n att: tonni bonde jeg skal have fixet nogle ting.", "tonni.bonde@gmail.com"),
    ("Til Tonni Bonde", "Hej tonni, jeg har brug for hjælp", "tonni.bonde@gmail.com")
])
def test(att_extractor, subject, body, expected_mail):
    mail = att_extractor.process(subject, body)
    assert mail == expected_mail
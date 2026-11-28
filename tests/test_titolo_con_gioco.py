import brain


def test_aggiunge_motogp_al_titolo_che_lo_dimentica():
    t = brain.titolo_con_gioco("Marquez si ritira: il clamoroso annuncio", "MotoGP")
    assert t == "MotoGP: Marquez si ritira: il clamoroso annuncio"
    assert brain.valida_titolo(t, "MotoGP")[0]


def test_lascia_stare_il_titolo_che_nomina_gia_il_gioco():
    t = "GP Valencia MotoGP: orari in TV"
    assert brain.titolo_con_gioco(t, "MotoGP") == t


def test_accorcia_il_resto_se_col_nome_sfora():
    lungo = "Marquez si ritira: il clamoroso annuncio dopo la vittoria finale"
    t = brain.titolo_con_gioco(lungo, "MotoGP")
    assert t.startswith("MotoGP: ")
    assert len(t) <= brain.MAX_CARATTERI_TITOLO


def test_nome_troppo_lungo_non_si_aggiunge():
    t = "Nuova fabbrica in Argentina"
    assert brain.titolo_con_gioco(t, "Stellantis diesel Multijet nuovo") == t


def test_senza_gioco_non_cambia_niente():
    assert brain.titolo_con_gioco("Titolo qualsiasi", "") == "Titolo qualsiasi"

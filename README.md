# Boränteagent Sverige

Personlig AI-agent som automatiskt samlar in, lagrar och analyserar svenska bolåneräntor över tid.

## Funktioner

- **Automatisk insamling** av listräntor från 8 svenska banker (SBAB, Swedbank, Handelsbanken, SEB, Nordea, Danske Bank, Länsförsäkringar, Skandia)
- **Referensräntor** från Riksbankens API: styrränta, STIBOR 3M, STIBOR 1W, statsobligationer
- **Historisk lagring** – ingen data skrivs över, all historik sparas i SQLite
- **Excel-export** med 6 flikar: Listräntor, Snitträntor, Referensräntor, Mina erbjudanden, Analys, Varningar
- **Terminal-dashboard** med Rich: marknadsöversikt, min lånesituation, besparingspotential
- **Varningssystem**: 6 kategorier av automatiska varningar
- **Schemalagd körning** kl. 07:00 svensk tid

## Installation

```bash
# Klona repot
git clone <repo-url>
cd borantor-agent-

# Skapa virtuell miljö
python -m venv venv
source venv/bin/activate      # Linux/Mac
# eller: venv\Scripts\activate  # Windows

# Installera beroenden
pip install -r requirements.txt
```

## Användning

```bash
# Hämta historiska referensräntor (kör en gång vid start)
python main.py backfill

# Samla in aktuella räntor
python main.py collect

# Visa dashboard i terminalen
python main.py dashboard

# Exportera Excel-rapport
python main.py export

# Kör varningskontroller
python main.py warnings

# Registrera eget erbjudande (interaktivt)
python main.py add-offer

# Kör allt på en gång (collect + warnings + export + dashboard)
python main.py run
```

## Automation

### Alternativ 1: Inbyggd schemaläggare

```bash
# Kör i bakgrunden – startar automatiskt kl. 07:00 varje dag
python scheduler.py &
```

### Alternativ 2: Cron (Linux/Mac)

```bash
crontab -e
# Lägg till:
0 7 * * * cd /path/to/borantor-agent- && /path/to/venv/bin/python main.py run >> data/borantor.log 2>&1
```

### Alternativ 3: Systemd service (Linux)

Skapa `/etc/systemd/system/borantor.service`:

```ini
[Unit]
Description=Boränteagent Sverige
After=network.target

[Service]
Type=simple
User=<ditt-användarnamn>
WorkingDirectory=/path/to/borantor-agent-
ExecStart=/path/to/venv/bin/python scheduler.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable borantor
sudo systemctl start borantor
```

### Alternativ 4: GitHub Actions (molnbaserat)

Se `.github/workflows/daily_collect.yml` (kan läggas till vid behov).

## Datalagring

Alla data sparas i `data/borantor.db` (SQLite). Tabeller:

| Tabell | Innehåll |
|--------|----------|
| `list_rates` | Bankernas listräntor |
| `avg_rates` | Bankernas snitträntor (om tillgängligt) |
| `reference_rates` | Riksbankens styrränta, STIBOR, statsobligationer |
| `my_offers` | Dina personliga erbjudanden |
| `warnings` | Genererade varningar |

## Varningskategorier

| Kategori | Beskrivning |
|----------|-------------|
| `RATE_ABOVE_LIST` | Din ränta är högre än bankens listränta |
| `RATE_ABOVE_AVG` | Din ränta är högre än bankens snittränta |
| `DISCOUNT_SHRINKING` | Din rabatt mot listräntan minskar |
| `BANK_MARGIN_INCREASING` | Bankens marginal ökar snabbare än styrräntan |
| `BETTER_BANK_AVAILABLE` | En annan bank erbjuder ≥0.20 pp lägre ränta |
| `HIGH_MARGIN_VS_REFERENCE` | Din räntemarginal mot styrränta/STIBOR är hög |

## Lägga till ny bank

1. Skapa `collectors/<banknamn>.py` baserat på ett befintligt collector-skript
2. Lägg till banken i `config.py` under `BANKS`
3. Importera och lägg till collectorn i `main.py` i `_build_collectors()`

## Projektstruktur

```
borantor-agent-/
├── main.py              # Huvudskript och CLI
├── scheduler.py         # Automatisk schemaläggare
├── config.py            # Konfiguration (banker, URL:er, inställningar)
├── requirements.txt
├── collectors/
│   ├── base_collector.py        # Basklass för alla insamlare
│   ├── sbab.py, swedbank.py...  # Bankspecifika insamlare
│   └── reference_rates.py       # Riksbankens API
├── storage/
│   ├── database.py              # SQLite-lager (append-only)
│   └── excel_exporter.py        # Excel-export
├── analysis/
│   ├── calculator.py            # Finansiella beräkningar
│   └── warnings.py              # Varningssystem
├── dashboard/
│   └── report.py                # Terminal-dashboard (Rich)
└── data/
    ├── borantor.db              # SQLite-databas (gitignorerad)
    ├── borantor_rapport.xlsx    # Excel-rapport (gitignorerad)
    └── borantor.log             # Loggfil (gitignorerad)
```

## Not om webbskrapning

Bankernas webbsidor ändras kontinuerligt. Om en bank inte returnerar räntor:

1. Öppna bankens räntesida i webbläsaren
2. Granska HTML-strukturen (högerklick → Inspektera)
3. Uppdatera motsvarande collector i `collectors/<bank>.py`

Riksbankens API (`api.riksbank.se/swea/v1`) är stabilt och dokumenterat.

## Framtida utvidgning

- Azure Functions + Azure Storage för molnbaserad körning
- Push-notiser (e-post/SMS) vid varningar
- Webb-dashboard med historiska grafer
- Integrering med Finansinspektionens bolånestatistik
- Automatisk PDF-rapport

# Source cross-reference vs. Ewan's portal list (Mappe1.xlsx, 2026-08-28)

## Confirmed — my source already equals (or is the machine-readable form of) yours
| Firm | Your link | Tracker source | Verdict |
|---|---|---|---|
| Rothschild | students-and-graduates/opportunities | same page (link_scrape) | identical — this is the fix from 11 Aug |
| Victoria Partners | talent-gesucht/praktikanten | same page (page_hash) | identical |
| Harris Williams | pnc.wd5 Workday HarrisWilliams | same Workday board (API) | mine = API behind your page |
| Stifel | jobs.50skills.com/stifel | 50skills JSON API | mine = API behind your page |
| Houlihan Lokey | hl.wd1 Workday Campus | same board (API), no location facets | mine is broader (all locations, filtered locally) |
| Alantra | alantra.com/careers/apply | alantra.wd3 Workday API | mine = system behind your page |
| Riverside | riversidecompany.com/jobs | Greenhouse API | mine = API behind your page |
| ING | careers.ing.com student filter | careers.ing.com sitemap | mine covers all Frankfurt, incl. student roles |
| Jefferies | jefferies.tal.net board | same board — NOW BOT-BLOCKED (Altcha) | manual checking required |

## Improved thanks to your list
| Firm | Change |
|---|---|
| Macquarie | added their intern-filtered feed (7959=[421070,421069]) as a second source — the location feeds alone were not surfacing internships |

## New firms added from your list
| Firm | Source | Status |
|---|---|---|
| RBC Capital Markets | jobs.rbc.com sitemap (index-following) | LIVE — 2027 Global IB Internship Frankfurt found |
| BNP Paribas CIB | bnpparibas.de jobs-sitemap | LIVE — 13 CIB internships incl. IB M&A Q3 2027 |

## Open follow-ups (from your list, not yet done)
- **Raymond James** — raymondjames.taleo.net (Taleo UK/Germany section). New firm, needs a Taleo fetcher.
- **Greenhill/Mizuho EMEA** — your link points to mizuhogroup.com/emea; the tracker watches the Mizuho **Americas** Workday board. EMEA internships may be posted elsewhere — same failure mode as the Rothschild miss. Needs verification.
- **Baird** — your link is the Europe IB intern programme page; tracker uses the Workday board. Confirm the programme is posted there when it opens.
- **SocGen** — your link uses their site search with jobType=Internship (Algolia-backed); would be cheaper/more precise than the current sitemap + per-page checks.

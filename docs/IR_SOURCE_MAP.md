# IR Source Map (verified on 2026-10-10)

This is early Phase P2 groundwork: what is reachable, what is blocked, and the exact
URL patterns. Every line here was tested from this Mac on 2026-10-10. Nothing is
assumed. Re-test before relying on it later.

## Summary

| Source | Page reachable | Document download | Verdict |
|---|---|---|---|
| ICICI Bank | yes, HTTP 200 | **works** | automatable |
| HDFC Bank | yes, HTTP 200 | **blocked, HTTP 403** | manual download |
| State Bank of India | yes, HTTP 200 | links are JS-rendered | manual download |
| RBI (www.rbi.org.in) | yes, HTTP 200 | n/a (HTML pages) | automatable |
| RBI (rbidocs PDFs) | n/a | **blocked, JS challenge** | manual download |
| RBI DBIE | JS application | not scrapable | manual download |

## ICICI Bank - works

- Correct IR page: `https://www.icicibank.com/about-us/investor-relations` (HTTP 200).
  Note: `/about-us/financial-results` returns **404** and `/investor-relations` returns **404**.
- Documents live on the CDN at:
  `https://www.icicibank.com/content/dam/icicibank/india/managed-assets/docs/about-us/<YEAR>/<FILE>.pdf`
  where `<YEAR>` is the **financial year label**, so FY2027 documents sit in `2027/`.
- Verified downloads (real PDFs, not HTML):
  - `2027/financial-results-q1-2027.pdf` - HTTP 200, 344,867 bytes
  - `2027/2026-07-Q1-2027-Investor-presentation.pdf` - HTTP 200, 989,175 bytes, 59 pages

## HDFC Bank - page readable, documents blocked

- IR listing page: `https://www.hdfcbank.com/personal/about-us/investor-relations/financial-results`
  (HTTP 200, ~1.5 MB). This page DOES contain the document links in plain HTML,
  so the file inventory can be harvested even though the files cannot be downloaded.
- Document base: `https://www.hdfcbank.com/content/dam/hdfcbankpws/in/en/pdf/about-us/financial-results/`
- Pattern: `<base>/<FY like 2026-2027>/quarter-<n>/<file>.pdf`
- 80 result documents harvested across all years; FY22-FY26/Q1FY27 subset is listed in
  `data/raw/MANUAL_DOWNLOAD_NEEDED.txt`.
- Blocked downloads (all with a full Chrome User-Agent):
  - `content/api/contentmanagement/DownloadFile?path=...` -> HTTP 000
  - direct `content/dam/...` URL -> HTTP 403, 8,117-byte HTML body
- Gap: Q2/Q3/Q4 documents for the older years are behind a JavaScript year-dropdown
  and are not present in the page HTML.

## State Bank of India - use sbi.bank.in

- Working entry: `https://sbi.bank.in/web/investor-relations/sbi-financial-highlights-past-5`
  (HTTP 200) - a single page with the 5-year financial highlights series.
- Also up: `https://sbi.bank.in/web/investor-relations/analyst-presentation`,
  `/annual-report`, and `https://sbi.co.in/web/investor-relations` (HTTP 200).
- Deleted/wrong paths: `sbi.co.in/web/investor-relations/financial-results` -> 404,
  `sbi.co.in/investor-relations` -> 404.
- Problem: result PDF links are not in the returned HTML (JavaScript-rendered).

## Reserve Bank of India

- HTML pages ARE readable, e.g. `https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx`.
- PDF host `rbidocs.rbi.org.in` returns HTTP 200 with `content-type: text/html` and a
  JavaScript bot-challenge body instead of the PDF. Downloads must be done in a browser.
- `data.rbi.org.in` (DBIE) is a JavaScript application.

## Machine facts (verified 2026-10-10)

- Apple M5, arm64, macOS 27.0.1 (build 26A434), zsh
- Anaconda at `/opt/anaconda3`, base Python 3.14.6, conda 26.9.1
  (`conda` is not on the non-interactive shell PATH - always use the absolute path)
- git 2.54.0
- Tableau **Public** (Apple silicon) is installed. Tableau Desktop is NOT installed.
- Node v24.20.0 available; poppler `pdftotext` NOT installed

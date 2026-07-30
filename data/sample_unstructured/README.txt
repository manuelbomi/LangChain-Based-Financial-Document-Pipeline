Synthetic sample data for UnstructuredFileConnector
====================================================

All *.txt files in this directory are synthetic, fictional documents about
"Northbridge Financial Group", an invented bank used only for this portfolio
demo. No real customer, employee, or institution data appears here.

File format (simple front matter + body, similar in spirit to Jekyll/Hugo
front matter but intentionally minimal):

    TITLE: <document title>
    CLASSIFICATION: public|internal|confidential|restricted
    EFFECTIVE_DATE: YYYY-MM-DD
    RETENTION_TAG: <retention policy id>
    ---
    <free-text document body>

Any header line may be omitted. `northbridge_incomplete_upload.txt` omits
CLASSIFICATION, EFFECTIVE_DATE, and RETENTION_TAG on purpose, to exercise
the pipeline's dead-letter routing for documents missing mandatory
governance metadata (see toolkit/validation.py and GOVERNANCE.md).

`northbridge_kyc_procedure.txt` contains obviously-fake SSN- and
account-number-shaped strings on purpose, to exercise the PII pattern
flagging in toolkit/validation.py. None of the values are real.

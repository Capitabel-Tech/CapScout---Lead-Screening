# Official Zoho CRM MCP: what was verified (2026-10-05)

Tested read-only plus one cleaned-up write test against the client's **testing** Zoho
(org "Alamaticz Solutions", India DC, Free edition, 3 users). All test records were
named `ZZ-TEST…` and deleted afterwards; the org was left with its original 8 Leads and
29 Meetings.

## Tools we will use (allow-list in the backend)
`upsertRecords` (only where safe, see below), `createRecords`, `updateRecord`, `searchRecords`,
`getRecord`, `getFields`, `getModules`. The connector also exposes `deleteRecord(s)`, `updateUser`,
`createFields` etc. The backend must never call those.

There is **no convert-lead tool** (`convertInventory` is for quotes/sales orders). "Convert to Lead"
in our app = create the Lead record in Zoho.

## Module facts
- Meetings module API name is **`Events`**. Mandatory: `Event_Title`, `Start_DateTime`,
  `End_DateTime`, `Meeting_Venue__s` (In-office / Client location / Online).
- Link meeting -> lead: send `"$se_module": "Leads"` and `"What_Id": {"id": "<lead id>"}`. **Verified.**
- Meeting with NO lead (Not Converted prospect): create without `What_Id`. **Verified**
  (`createRecords` accepts several records in one call).
- After conversion, link existing meetings in ONE call: `updateRecords` on Events with
  `[{"id": ..., "$se_module": "Leads", "What_Id": {"id": <lead id>}}, ...]`. **Verified.**
- Update a meeting by ID (`updateRecords`, e.g. Event_Title). **Verified.**
- Leads: only `Last_Name` is mandatory.

## Findings that change the design
1. **Upsert duplicate check is not reliable.** Upserting twice with
   `duplicate_check_fields: ["Last_Name"]` created TWO leads (both `action: insert`).
   => Never rely on upsert. Store the Zoho ID returned on create (`customers.zoho_lead_id`,
   `meetings.zoho_meeting_id`) and **update by ID** (`updateRecord`, verified).
   Before a first create, `searchRecords` by our own unique ID field to recover from a lost
   response (search by criteria verified).
2. **`Latitude` / `Longitude` on Events are not writable** (accepted, stored as null; they are
   filled by Zoho's check-in feature). Store GPS in custom fields and/or Description
   (e.g. a Google Maps link).
3. None of the 44 Excel fields exist in Zoho yet (only placeholder custom fields: Leads
   `Loan_Type`, `Assigned_to`; Events `Name1`, `Staff`, all "Option 1/2"). ~35 custom fields +
   unique `App_Customer_ID` (Leads) and `App_Meeting_ID` (Events) are needed. Zoho's built-in
   `Industry` / `Lead_Source` picklists do not match ours -> separate custom fields.
4. Free edition: custom-field and API limits unverified. Only 3 Zoho users, so all records
   belong to one owner; store the staff name in a text field.

## Still open
- Can the backend authenticate to the MCP server unattended (the docs describe a one-time browser
  OAuth login meant for AI clients)? Needs a test with a plain MCP client using the server URL.
- Zoho admin must create the custom fields (field list to be prepared).

## Live end-to-end test of the backend sync (2026-10-05)
Run through the real backend worker against the testing Zoho with a fake lead (`ZZ-TEST`):
- Not converted: meeting -> Zoho Meetings (Events), no Lead, no `What_Id`. OK
- Convert: Lead created once (Last_Name, Company, Mobile, City, Description snapshot), Zoho id saved,
  earlier meeting linked via `What_Id`. OK
- Meeting after conversion: Event linked to the Lead; Lead City/Description updated. OK
- All ZZ-TEST records were deleted from Zoho and from the app DB afterwards.
- Backend authenticates to the MCP server with the URL only once "Authorization via Connection"
  is enabled in the Zoho MCP console. Tools are exposed as `ZohoCRM_<name>`.
- Gotcha: this `mcp` library version names the result flag `is_error` (not `isError`).
- A `ZOHO_MCP_URL` rotation in the console needs a new paste into backend/.env.

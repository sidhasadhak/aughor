# Setting up the Google OAuth client — for reading comments on a Sheet, a Slides deck or a Doc

The user's call of 2026-10-27 (ROADMAP §6 item 54(f)): you create the client, guided. Aughor uses one Google app for every
Google card (Gmail, Sheets, Slides, Drive, Calendar, and now **Google Drive comments**). You set it up once, then connect
each card you want. Nothing here is pasted into a chat: the id and the secret go into Aughor's own form.

## 1 · In the Google Cloud console

1. Open <https://console.cloud.google.com/> and pick a project, or create one named **Aughor**.
2. **APIs & Services → Library**: enable **Google Drive API**. Enable **Google Sheets API** and **Google Slides API** too
   if you will use those cards.
3. **APIs & Services → OAuth consent screen** (Google now calls it *Google Auth Platform → Branding / Audience*):
   - **User type** — **Internal** if your account belongs to a Google Workspace organisation: only your organisation can
     use it, and Google does not review it. Otherwise **External**, left in **Testing**, with your own Google account
     added under **Test users**.
   - App name **Aughor**, your support email, your developer contact email.
   - **Scopes** (Data Access): add `openid`, `.../auth/userinfo.email` and `.../auth/drive.readonly`. Add
     `.../auth/spreadsheets.readonly` and `.../auth/presentations.readonly` only if you will use those cards.
     `drive.readonly` is what reading a file's comments needs; Google marks it *restricted*, which matters only for an
     External app published beyond its test users. Aughor reads only the one file a person names on a decision.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - **Application type**: Web application. **Name**: Aughor.
   - **Authorized redirect URIs**: add the address Aughor shows you in step 2 below. On this laptop install it is
     `http://localhost:8000/oauth/callback` — Google accepts `http://` for localhost.
   - Create, then copy the **Client ID** and the **Client secret**.

## 2 · In Aughor

1. **Operations → Integrations → Google → Set up**. Paste the Client ID and the Client secret, keep the redirect
   address it shows, and save. If Google later says *redirect_uri_mismatch*, the address in step 1.4 differs from the
   one this form shows — make them the same.
2. On the **Google Drive comments** card, press **Connect**. Google asks you to allow Aughor to see your Drive files;
   allow it. The card then says it is connected, with your account.
3. Nothing to switch on: once the client is set up and the card connected, a decision's **From Google** field reads.
   Until then it says which of the two is missing.

## 3 · Using it

On a decision's page, under **From Google**, paste a Sheets, Slides or Docs link and press **Read its comments**. Each
comment is kept on the decision in its author's name, with the cell, slide or quoted text it points at, as evidence that
arrived after the decision. Reading the same file again adds only what is new, and a comment edited since is restated.
No other file is listed, searched or read, and a comment never counts as an approval.

## If something goes wrong

- **"Not set up yet: this install has no Google OAuth client"** — step 2.1 is not done.
- **"Connect the Google Drive comments card first"** — step 2.2 is not done, or was done before the card existed.
- **"Google did not give the comments … insufficient permissions"** — the account you connected cannot open that file;
  share the file with it.
- **Access blocked: app not verified** — an External app in Testing allows only its listed test users; add yourself in
  step 1.3.

# Encore — setup guide

Every hour, Encore checks SeatGeek and Ticketmaster for popular **pop, adult contemporary, K-pop and comedy**
shows within 30 miles of **Houston, Dallas and Austin**. It does two things with what it finds:

- **Sends a notification to your phone** when something's worth your attention.
- **Updates your Encore dashboard**: a page you can add to your phone's home screen that works like an app.
  It lists every show Encore is watching, with prices, price trends, deals and upcoming sales. Tap a show to buy.

Encore never buys anything by itself. You tap and buy.

There are two budgets: **$200** for most shows, and **$350** for the very biggest acts and for K-pop.

**You'll get a notification when:**

- **Good seats fit your budget:** the *typical* (median) ticket price for a show drops to your budget or less.
  If half the listings are under $200, a good seat probably is too, not just the worst seat in the house.
- **The price drops:** the cheapest ticket falls 15% or more (and is within budget) since the last time it alerted you.

- **New show announced** (from Ticketmaster): a popular act in your genres adds a show near you.
  The alert lists face-value prices and presale and on-sale times.
- **Sale starts soon** (from Ticketmaster): a reminder about 24 hours before a presale or the public on-sale begins.
  Presales you can actually get into (your credit card, phone carrier, and so on) get a ⭐.
- **🔥 Last-minute drop:** in the final 2 days before a show, a smaller drop (10%) is enough to alert you,
  because resale prices often fall fast right before showtime.
- **Yearly heads-ups:** a reminder in mid-April about Live Nation's yearly $30 ticket sale, and one in early January
  to get your presale access ready before spring tours go on sale.

The first run sends **one summary** instead of dozens of alerts.

**Cost:** $0. **Time:** about 30–45 minutes, once. **You need:** a computer with a web browser,
and your phone. Nothing gets installed on the computer. Everything happens on websites.

---

## Part 1 — Notifications app on your phone (5 min)

1. On your phone, open the App Store (iPhone) or Play Store (Android) and install **ntfy**.
   The icon is a small speech bubble.
2. Open ntfy. Tap **+** (Subscribe to topic).
3. In **Topic name**, type your private topic name exactly. Claude gave you one in the chat
   (it looks like `ben-tix-` followed by random letters). Treat it like a password: anyone who knows it
   can see your alerts.
4. Leave the server as the default (`ntfy.sh`). Tap **Subscribe**.
5. If your phone asks to allow notifications, tap **Allow**.

## Part 2 — Get a SeatGeek API key (5 min)

This is a free key that lets the bot ask SeatGeek for prices the official, allowed way.

1. On your computer, go to **seatgeek.com** and log in. If you don't have an account, make one.
2. Go to **seatgeek.com/account/develop**.
3. Click the button to create or register a new app. Name it something like "Ben ticket alerts".
   For the website field, any placeholder like `https://example.com` is fine.
4. You'll see a **Client ID**, a long string of letters and numbers. Copy it into a note for now.
   (There may also be a "Client Secret". You don't need it.)

> SeatGeek's page might look a little different from this description. What you're looking for is the **Client ID**.

## Part 2b — Get a Ticketmaster API key (5 min)

Like SeatGeek's, this is a free and official key.

1. Go to **developer.ticketmaster.com** and click **Get your API key** (or **Sign up**).
   This account is separate from your normal Ticketmaster login.
2. Fill in the form. For company or website, put your name and `https://example.com`.
3. Confirm your email if it asks you to, then log in.
4. Click your name (top right) → **My Apps**. You should see an app that was created for you.
5. Copy the **Consumer Key** into your note. That's your API key.
   (Ignore the "Consumer Secret".)

> The bot still works without this key. It just won't send new-show or on-sale alerts.

## Part 3 — Make a GitHub account and a private project (10 min)

GitHub is a free website that runs the bot every hour on its own computers, so yours can stay off.

1. Go to **github.com** and click **Sign up**. Follow the steps and verify your email.
2. Once you're logged in, click the **+** in the top-right corner, then **New repository**.
3. **Repository name:** `encore`
4. Select **Public**. The free version of GitHub can only publish the dashboard page from a public project.
   Your keys and notification name stay private, because they're stored as secrets (Part 5).
   What anyone could see: the list of shows Encore watches, their prices and your settings file.
   Nothing in those is personal, but if you'd rather keep it private, GitHub Pro ($4/month) allows a private project.
5. Tick **Add a README file**.
6. Click **Create repository**.

## Part 4 — Upload the bot's files (10 min)

You have 5 files from Claude: `ticket_bot.py`, `config.json`, `dashboard_template.html`, `icon.png`
and `check-tickets.yml`. Download them to your computer first (they'll end up in your **Downloads** folder).

**Upload the first four:**
1. On your `encore` repository page, click **Add file** → **Upload files**.
2. Drag `ticket_bot.py`, `config.json`, `dashboard_template.html` and `icon.png` from your Downloads folder onto the page.
   (Or click **choose your files** and pick them.)
3. Scroll down and click the green **Commit changes** button.

**Create the schedule file.** This one has to go in a special folder, so you type it in instead of uploading it:
1. Click **Add file** → **Create new file**.
2. In the name box, type exactly: `.github/workflows/check-tickets.yml`.
   When you type each `/`, GitHub turns the part before it into a folder. That's expected.
3. Open `check-tickets.yml` on your computer. On Windows, right-click it → **Open with** → **Notepad**
   (if Notepad isn't listed, click **Choose another app** and pick it). Select everything (**Ctrl + A**),
   copy (**Ctrl + C**), then click into the big box on GitHub and paste (**Ctrl + V**).
   On a Mac, use **TextEdit** and **⌘ Command** instead of Ctrl.
4. Click **Commit changes…**, then **Commit changes** again in the pop-up.

## Part 5 — Add your two secrets (5 min)

Secrets are stored privately. They never show up in your files.

1. In your repository, click **Settings** (in the top tab bar, far right).
2. In the left sidebar: **Secrets and variables** → **Actions**.
3. Click **New repository secret**.
   - **Name:** `SEATGEEK_CLIENT_ID`
   - **Secret:** paste your SeatGeek Client ID
   - Click **Add secret**.
4. Click **New repository secret** again.
   - **Name:** `NTFY_TOPIC`
   - **Secret:** your ntfy topic name from Part 1 (exactly the same)
   - Click **Add secret**.
5. Click **New repository secret** one more time.
   - **Name:** `TICKETMASTER_API_KEY`
   - **Secret:** paste your Ticketmaster Consumer Key
   - Click **Add secret**.

Names have to match exactly: all capitals, underscores, no spaces.

## Part 5b — Turn on the dashboard page (2 min)

1. In your repository, click **Settings**, then **Pages** in the left sidebar.
2. Under **Build and deployment**, find **Source** and choose **GitHub Actions**.
   There's nothing to save. That's the whole step.

## Part 6 — Test it (5 min)

1. Click the **Actions** tab at the top of your repository.
   If you see a button saying workflows are disabled, click **I understand… enable them**.
2. In the left list, click **Encore - check ticket prices**.
3. On the right, click **Run workflow**. Tick **Only send a test notification to my phone**, then click
   the green **Run workflow** button.
4. Wait 30–60 seconds. Your phone should buzz with "Test from Encore". 🎉
5. Now do a real run: click **Run workflow** again, but **leave the box unticked**. In about a minute,
   you should get the "Encore is running" summary.

6. Open your dashboard. Its address is `https://YOUR-GITHUB-USERNAME.github.io/encore/`, with your
   GitHub username in place of `YOUR-GITHUB-USERNAME`. You can also find it under **Settings** → **Pages**,
   where GitHub shows "Your site is live at…". Bookmark it.

That's it. From here on, it runs every hour on its own. (GitHub sometimes runs scheduled jobs a bit late. That's normal.)

---

## Changing the settings

Click `config.json` in your repository, then the **pencil icon** ✏️ (top right of the file). Edit it, then click **Commit changes**.

| Setting | What it does |
|---|---|
| `max_price` | Your normal budget per ticket, in dollars (now 200) |
| `premium_max_price` | The higher budget for the biggest acts and K-pop (now 350) |
| `premium_min_popularity_score` | How popular a show must be (0 to 1) to get the higher budget. SeatGeek can't share box-office numbers, so popularity is the stand-in for "highest-grossing." Now 0.75. Lower it if your favorite big tours aren't getting the higher budget |
| `premium_genre_keywords` | Genres that always get the higher budget (now K-pop) |
| `drop_alert_percent` | How big a drop counts as a deal (15 = 15%) |
| `min_popularity_score` | How "hot" an act must be, from 0 to 1. **Lower it** (e.g. 0.4) to see more shows. **Raise it** (e.g. 0.65) for only the biggest names |
| `days_ahead` | How far into the future to look (180 days ≈ 6 months) |
| `radius_miles` | Distance around each city center (30 covers the suburbs and big venues) |
| `concert_genre_keywords` | Which music genres count |
| `always_watch` | Artists to always track, even if they fall outside the genres. Example: `["Coldplay", "Nate Bargatze"]` |
| `never_watch` | Artists to ignore. Example: `["Some Tribute Band"]` |
| `ticketmaster_classifications` | Which Ticketmaster categories to check (now Pop, K-Pop, Comedy) |
| `ticketmaster_min_artist_score` | How popular an artist must be on SeatGeek (0 to 1) before their new Ticketmaster shows alert you. Lower it if you're missing announcements, raise it if you get too many |
| `onsale_reminder_hours` | How early to remind you before a presale or on-sale (now 24 hours) |
| `presale_access` | Credit cards, phone carriers and clubs that get you into presales. Example: `["Citi", "Capital One", "Verizon", "Amex"]`. Presales whose name matches get a ⭐ |
| `final_days_before_show` | How many days before a show the last-minute rules start (now 2) |
| `final_drop_alert_percent` | How big a drop counts during those final days (now 10%) |
| `yearly_reminders` | Your yearly heads-ups. Each one has a `month`, `day`, `title`, `message` and `url`. Copy an existing one to add your own, for example for a festival's yearly on-sale |
| `max_alerts_per_run` | Most alerts sent per hour, so you don't get flooded |

Keep the quote marks, commas and brackets exactly as they are. If a run fails after you edit the file,
a missing comma or quote is usually the cause.

## Part 6b — Put Encore on your home screen (1 min)

On your iPhone, open your dashboard address in **Safari**. Tap the **Share** button (the square with an
arrow pointing up), scroll down, and tap **Add to Home Screen**, then **Add**. Encore now has its own icon
and opens full-screen like an app. (On Android, in Chrome: tap **⋮** → **Add to Home screen**.)

**Using the dashboard:**
- **Deals:** shows where a typical seat fits your budget. The price stub on the right turns **pink**.
- **All shows:** everything Encore is watching. Tap **Sorted by date** to switch to sorting by price.
- **On sale soon:** upcoming presales and on-sales, with a countdown. A ★ means you have access to that presale.
- **Alerts:** every notification Encore has sent you lately.
- Tap **Houston**, **Dallas** or **Austin** to hide or show that city, or use the search box.
- The small line on each show is the cheapest ticket's price since Encore started watching.

## Part 7 — Get presale access (15 min, optional but worth it)

The bot can tell you when a presale starts, but it can't get you into one. That part is up to you:

1. **List what you already have.** Check your wallet for cards that run presales (Citi, Capital One, Amex
   and Chase often do) and note your phone carrier (Verizon often has presales). Add them to `presale_access`
   in `config.json`, like `["Citi", "Verizon"]`.
2. **Join venue email lists.** Sign up for the newsletters on the websites for **Toyota Center** and
   **Cynthia Woods Mitchell Pavilion** (Houston), **Moody Center** (Austin) and **American Airlines Center** (Dallas).
   Their emails often include presale codes.
3. **Follow your must-see artists.** On Ticketmaster, tap the heart next to an artist. Also sign up on their own
   websites. Artist presale codes usually go to their email lists.

## If something goes wrong

On the **Actions** tab, a red ❌ means a run failed. Click it, then click **check**, and read the step marked with the red X.

- **"SeatGeek said 401" or "403":** the Client ID secret is wrong. Redo Part 5, step 3.
- **"Ticketmaster said 401":** the Ticketmaster key secret is wrong. Redo Part 5, step 5.
  The SeatGeek alerts keep working in the meantime.
- **"NTFY_TOPIC is not set" or "SEATGEEK_CLIENT_ID is not set":** a secret's name is misspelled.
- **The run is green but no notification shows up:** the topic in the ntfy app doesn't exactly match the `NTFY_TOPIC` secret.
- **"Permission denied" on the "Save price history" step:** go to **Settings** → **Actions** → **General** →
  scroll to **Workflow permissions** → choose **Read and write permissions** → **Save**.
- **The dashboard link shows "404":** check Part 5b, then run the workflow once more (Part 6, step 5).
  Give it a minute after the run finishes.
- **The "Publish the dashboard" step fails:** check that the repository is **Public** (Settings → General,
  at the very bottom under "Danger Zone", **Change visibility**) and that Part 5b is done.
- **Too many or too few alerts:** adjust `min_popularity_score` or `max_price` in `config.json`.

**To pause Encore:** **Actions** tab → **Encore - check ticket prices** → **⋯** (top right) → **Disable workflow**. Turn it back on the same way.

## Good to know

- The bot only tracks resale prices on **SeatGeek**. Ticketmaster (and StubHub) can be cheaper for the same show,
  so check them quickly before you buy.
- Presales usually need a code from the artist's fan club, a credit card, or the venue's email list (see Part 7).
- The Live Nation $30 sale reminder is just a date-based heads-up. The bot can't see those deals,
  so open the link and check which shows are included.
- SeatGeek tells the bot the cheapest and typical prices, but not *which section* the seats are in.
  Open the link to check where the seats actually are.
- The file `state.json` is Encore's memory of past prices. It updates itself every hour, so don't edit it.

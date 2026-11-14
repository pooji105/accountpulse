# Walkthrough script (3:00) - record only after you have checked each step on your live site

**0:00-0:30 Intro.** "This is AccountPulse, a live CRM for my two accounts, Eastern Counties Police Alliance and Aldermoor Industrial Group. It reads my data from the Questathon MCP, and every number links to its source." Show the Overview page and the sync status line.

**0:30-1:15 Both accounts, five questions.** Open the first account page and scroll: book worth (verified vs unverified vs uncertain), power map, top three actions with owner and due, risks, knowledge gaps. Switch to the second account and show the same five sections.

**1:15-1:45 Trace one number.** In Deal Intelligence pick one deal value. Click its evidence ID and show the record, source type and fact status. Point out the morning-snapshot column and that claims are not counted as verified.

**1:45-2:20 New live event.** Open Live Events. Show the detected events and the notification. Say the page polls get_signals itself. If a new event arrives during the recording, show it appear along with its new risk and action; otherwise show the existing Calder/Westmere/usage events and say so.

**2:20-2:45 Write a note.** Notes & Activity: choose an account, kind next_step, write a note, save. Show it queued, then saved after the next API slot (up to about a minute).

**2:45-3:00 Tech.** "Flask backend, a 62-second rate-limited scheduler, JSON cache, HTML/CSS/JS with Chart.js, deployed on Render. The token stays on the server."

Before recording: confirm every feature above works on your deployed site. Do not claim anything you did not see work.

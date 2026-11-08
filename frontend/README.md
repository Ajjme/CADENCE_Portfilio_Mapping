# CADENCE frontend

The React version of the CADENCE app. It only shows things - the analysis
itself runs in Python, behind the FastAPI backend.

## Run it locally

Needs Node.js (the LTS version). From this `frontend` folder:

```
npm install   # once, and again after package.json changes
npm run dev   # opens at http://localhost:5173 and reloads as you edit
```

## Other commands

| Command          | What it does                                                       |
| ---------------- | ------------------------------------------------------------------ |
| `npm test`       | Runs the tests once (`npm run test:watch` reruns them as you edit) |
| `npm run lint`   | Flags common mistakes                                              |
| `npm run format` | Formats every file with Prettier                                   |
| `npm run build`  | Type-checks and builds the static site into `dist/`                |

## Where things live

```
src/
  main.tsx      starts the app and applies the theme
  App.tsx       header, sidebar, and which page is showing
  theme.ts      colors and fonts
  pages/        one file per screen, matching the Streamlit pages
  components/   pieces used on more than one page
  api/          every call to the backend
  test/         test setup
```

Each page reads top to bottom in the same order as the screen, like a Streamlit
script. A fuller guide for reading this code if you know Streamlit is coming.

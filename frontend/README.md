# CADENCE frontend

The React version of the CADENCE app. It only shows things - the analysis
itself runs in Python, behind the FastAPI backend.

## Run it locally

Needs Node.js (the LTS version). From this `frontend` folder:

```
npm install   # once, and again after package.json changes
npm run dev   # opens at http://localhost:5173 and reloads as you edit
```

The pages get their data from the FastAPI backend, so start it first in a
second terminal. From the `CADENCE` folder:

```
python -m uvicorn cadence.api.main:app --reload --app-dir src
```

`npm run dev` passes every `/api` request on to it. The backend's own page at
http://127.0.0.1:8000/docs lists every call.

## Other commands

| Command             | What it does                                                       |
| ------------------- | ------------------------------------------------------------------ |
| `npm test`          | Runs the tests once (`npm run test:watch` reruns them as you edit) |
| `npm run lint`      | Flags common mistakes                                              |
| `npm run format`    | Formats every file with Prettier                                   |
| `npm run build`     | Type-checks and builds the static site into `dist/`                |
| `npm run api:types` | Regenerates the backend types (see `src/api/README.md`)            |

## Where things live

```
src/
  main.tsx      starts the app and applies the theme
  App.tsx       header, sidebar, and which page is showing
  theme.ts      colors and fonts
  pages/        one file per screen, matching the Streamlit pages
    results/    the Results page's tabs, one file each
  components/   pieces used on more than one page
  api/          every call to the backend
  test/         test setup
```

Each page reads top to bottom in the same order as the screen, like a Streamlit
script. A fuller guide for reading this code if you know Streamlit is coming.

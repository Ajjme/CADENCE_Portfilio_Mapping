# api/

Every call to the FastAPI backend lives here, one function per call. Pages call
these functions and never build URLs themselves.

| File           | What's in it                                                      |
| -------------- | ----------------------------------------------------------------- |
| `client.ts`    | What every call shares: the backend address and error messages    |
| `settings.ts`  | Default run settings, for the settings form                       |
| `portfolio.ts` | The example workbook and uploading a workbook                     |
| `runs.ts`      | Running an analysis and reading its results                       |
| `schema.d.ts`  | Types for every request and reply, generated - don't edit by hand |

## Using a call on a page

Pages load data with TanStack Query's `useQuery`, which handles loading, errors,
and keeping results so they aren't fetched twice (like `st.cache_data`):

```tsx
const summary = useQuery({
  queryKey: ['summary', runId],
  queryFn: () => getRunSummary(runId),
})
if (summary.isPending) return <Loader />
if (summary.isError) return <Alert color="red">{summary.error.message}</Alert>
// summary.data is a Schemas['RunSummary'], so the editor knows every field.
```

For something that changes data, like running an analysis, use `useMutation`.

## When the backend changes

The types come from the backend's Python models, so a change there shows up
here as a type error instead of a bug. After changing an endpoint or a model in
`CADENCE/src/cadence/api`:

1. From the `CADENCE` folder, write the backend's schema to `frontend/openapi.json`:

   ```
   python -m cadence.api.write_openapi
   ```

2. From the `frontend` folder, regenerate the types:

   ```
   npm run api:types
   ```

3. Run `npm run build` to see what the change broke, and fix it.

Commit `openapi.json` and `schema.d.ts` with the backend change. The backend
tests check that `openapi.json` matches the API, so a forgotten step 1 fails
`python -m pytest`.

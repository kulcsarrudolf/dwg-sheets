# Translations

The web app is in English, Romanian and Hungarian.
English is the source language and the default.
This document is for anyone who edits a translation or adds a language.

## Where the texts are

| File | What it is |
|---|---|
| `src/dwg_sheets_to_pdf/web/locales/messages.pot` | The template: every English text the app shows. Generated, never edited by hand. |
| `src/dwg_sheets_to_pdf/web/locales/ro/LC_MESSAGES/messages.po` | Romanian |
| `src/dwg_sheets_to_pdf/web/locales/hu/LC_MESSAGES/messages.po` | Hungarian |

These are standard gettext files.
Open a `.po` file in a translation editor such as [Poedit](https://poedit.net/), or in any text editor.
The app reads the `.po` files when it starts, so there is no compile step: save the file and restart the app.

## Editing a translation

Each entry is the English text (`msgid`) followed by its translation (`msgstr`):

```po
msgid "Download all (ZIP)"
msgstr "Descarca tot (ZIP)"
```

Keep these parts exactly as they are in the English text:

- **Placeholders** such as `%(mb)s`, `%(count)s`, `%(name)s`.
  They are replaced with numbers and names when the page is shown.
  Their order may change to fit the sentence, but each one must stay.
- **File types and codes**: `.dwg`, `.dxf`, `ZIP`, `PDF`, `PL. NR.`, `SCARA 1:N`, `1:100`.
  `PL. NR.` and `SCARA` are written exactly like that in the title blocks of the drawings.

Texts with a number have one line per plural form.
Romanian has three forms, Hungarian one:

```po
msgid "%(count)s sheet"
msgid_plural "%(count)s sheets"
msgstr[0] "%(count)s plansa"       # 1
msgstr[1] "%(count)s planse"       # 0, 2-19
msgstr[2] "%(count)s de planse"    # 20 and more
```

Numbers on the page (page sizes, counts) are formatted for each language automatically: `1,633.6` in English, `1.633,6` in Romanian, `1 633,6` in Hungarian.

## House rules

- **Romanian is written without diacritics** (`a i s t`, not `ă â î ș ț`).
  A test fails if one slips in.
- Use the terms architects and engineers use on drawings:

| English | Romanian | Hungarian |
|---|---|---|
| sheet | plansa | tervlap |
| title block | cartus | szövegmező |
| scale | scara | méretarány |
| frame, border | chenar | keret |
| to plot | a plota | plottolni |

- Address the reader politely: `dumneavoastra` forms in Romanian (`Alegeti`, `Incarcati`), `Ön` forms in Hungarian (`Válasszon`, `Húzzon`).
- Keep the tone short and plain. Buttons say what they do (`Descarca`, `Letöltés`).

## After the English text changes

When a developer adds or changes text in the code or the templates, update the template and both catalogs:

```sh
uv run pybabel extract -F babel.cfg -k N_ --no-wrap -o src/dwg_sheets_to_pdf/web/locales/messages.pot .
uv run pybabel update -i src/dwg_sheets_to_pdf/web/locales/messages.pot -d src/dwg_sheets_to_pdf/web/locales --no-wrap
```

`update` adds the new texts with an empty `msgstr`, and marks texts whose English changed as `#, fuzzy`.
Translate the empty ones, check the fuzzy ones and remove their `#, fuzzy` line.
Fuzzy and empty entries show in English until then.

The tests check that:

- the template matches the texts in the code and templates (run `extract` if it fails),
- every text is translated in every language, with no fuzzy entries,
- every translation keeps the placeholders of its English text,
- Romanian has no diacritics.

## Adding a language

1. Create its catalog, for example German:

   ```sh
   uv run pybabel init -i src/dwg_sheets_to_pdf/web/locales/messages.pot -d src/dwg_sheets_to_pdf/web/locales -l de --no-wrap
   ```

2. Translate every entry in `locales/de/LC_MESSAGES/messages.po`.
3. Add the language to `LANGUAGES` in `src/dwg_sheets_to_pdf/web/i18n.py`, with its name in its own language.
   The switcher in the page header shows it from then on.
4. Add it to the language list in the tests (`tests/test_i18n.py`).

## How the page picks a language

1. `?lang=ro` in the address. Choosing a language in the switcher does this, and the choice is remembered in a cookie for a year.
2. The remembered choice.
3. The browser's preferred languages, in order.
4. English.

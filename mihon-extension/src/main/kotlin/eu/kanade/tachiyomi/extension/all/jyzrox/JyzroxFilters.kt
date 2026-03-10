package eu.kanade.tachiyomi.extension.all.jyzrox

import eu.kanade.tachiyomi.source.model.Filter

class SourceFilter : Filter.Select<String>(
    "Source",
    arrayOf("All", "ehentai", "pixiv"),
)

class RatingFilter : Filter.Select<String>(
    "Min Rating",
    arrayOf("Any", "1", "2", "3", "4", "5"),
)

class FavoritesFilter : Filter.CheckBox("Favorites only", false)

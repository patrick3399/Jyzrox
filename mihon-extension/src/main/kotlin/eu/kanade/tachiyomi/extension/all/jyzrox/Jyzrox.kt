package eu.kanade.tachiyomi.extension.all.jyzrox

import android.app.Application
import android.content.SharedPreferences
import androidx.preference.EditTextPreference
import androidx.preference.PreferenceScreen
import eu.kanade.tachiyomi.network.GET
import eu.kanade.tachiyomi.source.ConfigurableSource
import eu.kanade.tachiyomi.source.model.FilterList
import eu.kanade.tachiyomi.source.model.MangasPage
import eu.kanade.tachiyomi.source.model.Page
import eu.kanade.tachiyomi.source.model.SChapter
import eu.kanade.tachiyomi.source.model.SManga
import eu.kanade.tachiyomi.source.online.HttpSource
import kotlinx.serialization.json.Json
import okhttp3.Headers
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import uy.kohesive.injekt.Injekt
import uy.kohesive.injekt.api.get
import java.text.SimpleDateFormat
import java.util.Locale

class Jyzrox : HttpSource(), ConfigurableSource {

    override val name = "Jyzrox"
    override val lang = "all"
    override val supportsLatest = true

    private val preferences: SharedPreferences by lazy {
        Injekt.get<Application>().getSharedPreferences("source_$id", 0x0000)
    }

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    override val baseUrl: String
        get() = preferences.getString(PREF_SERVER_URL, "http://localhost:35689")!!.trimEnd('/')

    private val apiToken: String
        get() = preferences.getString(PREF_API_TOKEN, "") ?: ""

    override val client: OkHttpClient = network.cloudflareClient

    // ── Headers ─────────────────────────────────────────────────────

    override fun headersBuilder(): Headers.Builder = super.headersBuilder().apply {
        if (apiToken.isNotBlank()) {
            add("X-API-Token", apiToken)
        }
    }

    private val apiBase: String get() = "$baseUrl/api/external/v1"

    // ── Popular (all galleries) ─────────────────────────────────────

    override fun popularMangaRequest(page: Int): Request {
        val url = "$apiBase/galleries?page=${page - 1}&limit=$PAGE_SIZE"
        return GET(url, headers)
    }

    override fun popularMangaParse(response: Response): MangasPage {
        val body = response.body.string()
        val result = json.decodeFromString<GalleriesResponse>(body)
        val mangas = result.galleries.map { it.toSManga(baseUrl) }
        val hasNext = (result.page + 1) * PAGE_SIZE < result.total
        return MangasPage(mangas, hasNext)
    }

    // ── Latest (same endpoint, sorted by added_at) ──────────────────

    override fun latestUpdatesRequest(page: Int): Request {
        val url = "$apiBase/galleries?page=${page - 1}&limit=$PAGE_SIZE"
        return GET(url, headers)
    }

    override fun latestUpdatesParse(response: Response): MangasPage =
        popularMangaParse(response)

    // ── Search ──────────────────────────────────────────────────────

    override fun searchMangaRequest(page: Int, query: String, filters: FilterList): Request {
        val url = "$apiBase/galleries".toHttpUrl().newBuilder().apply {
            addQueryParameter("page", (page - 1).toString())
            addQueryParameter("limit", PAGE_SIZE.toString())

            if (query.isNotBlank()) {
                addQueryParameter("q", query)
            }

            filters.forEach { filter ->
                when (filter) {
                    is SourceFilter -> {
                        val value = filter.values[filter.state]
                        if (value != "All") addQueryParameter("source", value)
                    }
                    is RatingFilter -> {
                        val value = filter.values[filter.state]
                        if (value != "Any") addQueryParameter("min_rating", value)
                    }
                    is FavoritesFilter -> {
                        if (filter.state) addQueryParameter("favorited", "true")
                    }
                    else -> {}
                }
            }
        }.build().toString()

        return GET(url, headers)
    }

    override fun searchMangaParse(response: Response): MangasPage =
        popularMangaParse(response)

    override fun getFilterList(): FilterList = FilterList(
        SourceFilter(),
        RatingFilter(),
        FavoritesFilter(),
    )

    // ── Manga details ───────────────────────────────────────────────

    override fun mangaDetailsRequest(manga: SManga): Request {
        val id = manga.url.substringAfterLast("/")
        return GET("$apiBase/galleries/$id", headers)
    }

    override fun mangaDetailsParse(response: Response): SManga {
        val body = response.body.string()
        val gallery = json.decodeFromString<GalleryDto>(body)
        return gallery.toSManga(baseUrl)
    }

    // ── Chapter list (1 chapter per gallery) ────────────────────────

    override fun chapterListRequest(manga: SManga): Request =
        mangaDetailsRequest(manga)

    override fun chapterListParse(response: Response): List<SChapter> {
        val body = response.body.string()
        val gallery = json.decodeFromString<GalleryDto>(body)

        val chapter = SChapter.create().apply {
            url = "/galleries/${gallery.id}/images"
            name = gallery.title ?: gallery.titleJpn ?: "Chapter 1"
            chapter_number = 1f
            date_upload = parseDate(gallery.addedAt)
        }
        return listOf(chapter)
    }

    // ── Page list ───────────────────────────────────────────────────

    override fun pageListRequest(chapter: SChapter): Request {
        // chapter.url = /galleries/{id}/images
        return GET("$apiBase${chapter.url}", headers)
    }

    override fun pageListParse(response: Response): List<Page> {
        val body = response.body.string()
        val result = json.decodeFromString<ImagesResponse>(body)

        return result.images.mapIndexed { index, img ->
            // Use the API file endpoint so X-API-Token auth works
            val imageUrl = if (img.fileUrl != null) {
                "$baseUrl${img.fileUrl}"
            } else {
                // Fallback to streaming endpoint
                "$apiBase/galleries/${result.galleryId}/images/${img.pageNum}/file"
            }
            Page(index, "", imageUrl)
        }
    }

    override fun imageUrlParse(response: Response): String =
        throw UnsupportedOperationException("Not used — imageUrl is set directly in pageListParse")

    override fun imageRequest(page: Page): Request {
        // Add X-API-Token header for image requests through the API
        return GET(page.imageUrl!!, headers)
    }

    // ── Settings ────────────────────────────────────────────────────

    override fun setupPreferenceScreen(screen: PreferenceScreen) {
        EditTextPreference(screen.context).apply {
            key = PREF_SERVER_URL
            title = "Server URL"
            summary = "Jyzrox instance URL (e.g. https://gallery.example.com)"
            setDefaultValue("http://localhost:35689")
        }.let(screen::addPreference)

        EditTextPreference(screen.context).apply {
            key = PREF_API_TOKEN
            title = "API Token"
            summary = "Generated from Settings page in Jyzrox web UI"
            setDefaultValue("")
        }.let(screen::addPreference)
    }

    // ── Helpers ─────────────────────────────────────────────────────

    private fun parseDate(dateStr: String?): Long {
        if (dateStr == null) return 0L
        return try {
            DATE_FORMAT.parse(dateStr)?.time ?: 0L
        } catch (_: Exception) {
            0L
        }
    }

    companion object {
        private const val PREF_SERVER_URL = "server_url"
        private const val PREF_API_TOKEN = "api_token"
        private const val PAGE_SIZE = 25

        private val DATE_FORMAT = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
    }
}

// ── Extension function ──────────────────────────────────────────────

private fun GalleryDto.toSManga(baseUrl: String): SManga = SManga.create().apply {
    url = "/galleries/$id"
    title = this@toSManga.title ?: titleJpn ?: "Gallery $id"
    author = uploader
    artist = uploader
    description = buildString {
        if (category != null) append("Category: $category\n")
        if (language != null) append("Language: $language\n")
        if (pages != null) append("Pages: $pages\n")
        if (rating != null && rating > 0) append("Rating: $rating/5\n")
        if (source != null) append("Source: $source")
    }
    genre = tags.joinToString(", ")
    status = SManga.COMPLETED
    thumbnail_url = null // Cover thumbnails require cookie auth; Mihon can't use them directly
    initialized = true
}

package eu.kanade.tachiyomi.extension.all.jyzrox

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class GalleriesResponse(
    val total: Int,
    val page: Int,
    val galleries: List<GalleryDto>,
)

@Serializable
data class GalleryDto(
    val id: Int,
    val source: String? = null,
    @SerialName("source_id") val sourceId: String? = null,
    val title: String? = null,
    @SerialName("title_jpn") val titleJpn: String? = null,
    val category: String? = null,
    val language: String? = null,
    val pages: Int? = null,
    @SerialName("posted_at") val postedAt: String? = null,
    @SerialName("added_at") val addedAt: String? = null,
    val rating: Int? = null,
    val favorited: Boolean = false,
    val uploader: String? = null,
    @SerialName("download_status") val downloadStatus: String? = null,
    val tags: List<String> = emptyList(),
)

@Serializable
data class ImagesResponse(
    @SerialName("gallery_id") val galleryId: Int,
    val images: List<ImageDto>,
)

@Serializable
data class ImageDto(
    val id: Int,
    @SerialName("page_num") val pageNum: Int,
    val filename: String? = null,
    val width: Int? = null,
    val height: Int? = null,
    @SerialName("file_size") val fileSize: Long? = null,
    @SerialName("media_type") val mediaType: String? = null,
    @SerialName("file_url") val fileUrl: String? = null,
    @SerialName("thumb_url") val thumbUrl: String? = null,
)

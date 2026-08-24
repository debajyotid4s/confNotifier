package com.call4paper.app.ui.conference

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.mappers.toEntity
import com.call4paper.app.data.remote.ApiService
import com.call4paper.app.data.repository.ConferenceRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ConferenceUiState(
    val conference: ConferenceEntity? = null,
    val bookmarked: Boolean = false,
    val isRefreshing: Boolean = false,
    val bookmarkError: String? = null
)

@HiltViewModel
class ConferenceViewModel @Inject constructor(
    private val repo: ConferenceRepository,
    private val api: ApiService
) : ViewModel() {
    private val _state = MutableStateFlow(ConferenceUiState())
    val state: StateFlow<ConferenceUiState> = _state.asStateFlow()
    private var currentId: Int = -1

    fun load(id: Int) {
        currentId = id
        viewModelScope.launch {
            _state.update { it.copy(isRefreshing = true, bookmarkError = null) }
            try {
                val dto = api.getConference(id)
                _state.update { it.copy(conference = dto.toEntity(), bookmarked = dto.bookmarked == true, isRefreshing = false) }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                val cached = repo.getDetail(id)
                _state.update { it.copy(conference = cached, isRefreshing = false) }
            }
        }
    }

    fun refresh() { if (currentId != -1) load(currentId) }

    fun toggleBookmark(id: Int) {
        viewModelScope.launch {
            _state.update { it.copy(bookmarkError = null) }
            try {
                val wasBookmarked = _state.value.bookmarked
                if (wasBookmarked) api.removeBookmark(id) else api.addBookmark(id)
                _state.update { it.copy(bookmarked = !wasBookmarked) }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                _state.update { it.copy(bookmarkError = "Bookmark failed — check your connection") }
            }
        }
    }

    fun clearBookmarkError() { _state.update { it.copy(bookmarkError = null) } }
}

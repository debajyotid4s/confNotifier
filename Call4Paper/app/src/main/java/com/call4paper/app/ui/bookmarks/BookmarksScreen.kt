package com.call4paper.app.ui.bookmarks

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.remote.ApiService
import com.call4paper.app.data.local.ConferenceEntity
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class BookmarksViewModel @Inject constructor(private val api: ApiService) : ViewModel() {
    private val _items = mutableStateOf<List<ConferenceEntity>>(emptyList())
    val items: List<ConferenceEntity> get() = _items.value
    private val _loading = mutableStateOf(false)
    val loading: Boolean get() = _loading.value
    private val _error = mutableStateOf<String?>(null)
    val error: String? get() = _error.value

    fun refresh() {
        viewModelScope.launch {
            _loading.value = true
            _error.value = null
            try {
                val dtos = api.getBookmarks()
                _items.value = dtos.map {
                    ConferenceEntity(
                        id = it.id, title = it.name, website = it.website,
                        startDate = it.start_date, endDate = it.end_date,
                        city = it.location, organizer = it.organizer, category = it.category,
                        abstractDeadline = it.abstract_deadline, fullPaperDeadline = it.full_paper_deadline
                    )
                }
            } catch (_: Exception) {
                _error.value = "Could not load bookmarks — check your connection"
            }
            _loading.value = false
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun BookmarksScreen(onConference: (Int) -> Unit, vm: BookmarksViewModel = hiltViewModel()) {
    LaunchedEffect(Unit) { vm.refresh() }
    PullToRefreshBox(isRefreshing = vm.loading, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text("Bookmarks", style = MaterialTheme.typography.titleLarge, fontSize = 20.sp)
            Spacer(Modifier.height(8.dp))
            if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) }
            if (!vm.loading && vm.items.isEmpty() && vm.error == null) {
                Text("No bookmarks yet — tap ♡ on a conference to save it", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxSize().padding(top = 8.dp)) {
                items(vm.items, key = { it.id }) { c ->
                    Card(Modifier.fillMaxWidth().clickable { onConference(c.id) }) {
                        Column(Modifier.padding(12.dp)) {
                            Text(c.title, fontSize = 14.sp)
                            Text(c.startDate ?: "", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

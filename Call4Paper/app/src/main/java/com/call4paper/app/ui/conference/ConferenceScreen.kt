package com.call4paper.app.ui.conference

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.remote.ApiService
import com.call4paper.app.data.repository.ConferenceRepository
import com.call4paper.app.ui.theme.urgencyForEntity
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class ConferenceViewModel @Inject constructor(private val repo: ConferenceRepository, private val api: ApiService) : ViewModel() {
    private val _bookmarked = MutableStateFlow(false)
    val bookmarked: StateFlow<Boolean> = _bookmarked
    private val _conference = MutableStateFlow<com.call4paper.app.data.local.ConferenceEntity?>(null)
    val conference: StateFlow<com.call4paper.app.data.local.ConferenceEntity?> = _conference
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing
    private val _bookmarkError = MutableStateFlow<String?>(null)
    val bookmarkError: StateFlow<String?> = _bookmarkError
    private var currentId: Int = -1

    fun load(id: Int) {
        currentId = id
        viewModelScope.launch {
            _isRefreshing.value = true
            _bookmarkError.value = null
            _conference.value = repo.getDetail(id)
            try {
                val resp = api.getBookmark(id)
                _bookmarked.value = resp["bookmarked"] == true
            } catch (e: Exception) {
                android.util.Log.w("ConferenceVM", "getBookmark failed for $id", e)
                try { api.getBookmarks().let { list -> _bookmarked.value = list.any { it.id == id } } } catch (e2: Exception) {
                    android.util.Log.w("ConferenceVM", "getBookmarks fallback failed", e2)
                }
            }
            _isRefreshing.value = false
        }
    }
    fun refresh() { if (currentId != -1) load(currentId) }
    fun toggleBookmark(id: Int) {
        viewModelScope.launch {
            _bookmarkError.value = null
            try {
                if (_bookmarked.value) { api.removeBookmark(id); _bookmarked.value = false } else { api.addBookmark(id); _bookmarked.value = true }
            } catch (e: Exception) {
                android.util.Log.e("ConferenceVM", "toggleBookmark failed for $id", e)
                _bookmarkError.value = "Bookmark failed — check your connection"
            }
        }
    }
    fun clearBookmarkError() { _bookmarkError.value = null }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConferenceScreen(id: Int, vm: ConferenceViewModel = hiltViewModel()) {
    val c by vm.conference.collectAsState()
    val bm by vm.bookmarked.collectAsState()
    val isRefreshing by vm.isRefreshing.collectAsState()
    val bookmarkError by vm.bookmarkError.collectAsState()
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val snackbarHost = remember { SnackbarHostState() }
    LaunchedEffect(bookmarkError) { bookmarkError?.let { snackbarHost.showSnackbar(it); vm.clearBookmarkError() } }
    LaunchedEffect(id) { vm.load(id) }
    Scaffold(snackbarHost = { SnackbarHost(snackbarHost) }) { pad ->
        PullToRefreshBox(isRefreshing = isRefreshing, onRefresh = { vm.refresh() }, modifier = Modifier.fillMaxSize().padding(pad)) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp).windowInsetsPadding(androidx.compose.foundation.layout.WindowInsets.statusBars),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                if (c == null && isRefreshing) {
                    Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                } else if (c == null) {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(32.dp))
                            Text("Couldn't load conference", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onErrorContainer)
                            Text("Pull to refresh or check your connection", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
                            Button(onClick = { vm.refresh() }, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
                        }
                    }
                } else {
                    val urgency = urgencyForEntity(c!!)
                    Card(
                        shape = RoundedCornerShape(12.dp),
                        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                            Box(Modifier.width(4.dp).fillMaxHeight().background(urgency))
                            Column(Modifier.padding(16.dp).weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text(c!!.title, style = MaterialTheme.typography.headlineSmall)
                                val dl = c!!.abstractDeadline ?: c!!.fullPaperDeadline
                                val label = when {
                                    c!!.abstractDeadline != null -> "Abstract"
                                    c!!.fullPaperDeadline != null -> "Full paper"
                                    else -> null
                                }
                                if (dl != null && label != null) {
                                    Text("$label: $dl", style = MaterialTheme.typography.labelMedium, color = urgency)
                                }
                                Text(
                                    listOfNotNull(c!!.city, c!!.organizer).joinToString(" · ").ifEmpty { c!!.category ?: "" },
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                c!!.website?.let {
                                    Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, maxLines = 1)
                                }
                            }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = { vm.toggleBookmark(id) }, shape = RoundedCornerShape(12.dp), modifier = Modifier.weight(1f)) {
                            Text(if (bm) "Bookmarked" else "Bookmark")
                        }
                        OutlinedButton(
                            onClick = { c?.website?.let { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it))) } },
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.weight(1f)
                        ) { Text("Official Website") }
                    }
                }
            }
        }
    }
}

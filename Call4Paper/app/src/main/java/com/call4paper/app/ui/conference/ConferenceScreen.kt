package com.call4paper.app.ui.conference

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.remote.ApiService
import com.call4paper.app.data.repository.ConferenceRepository
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

    fun load(id: Int) {
        viewModelScope.launch {
            _conference.value = repo.getDetail(id)
            try { api.getBookmarks().let { list -> _bookmarked.value = list.any { it.id == id } } } catch (_: Exception) {}
        }
    }
    fun toggleBookmark(id: Int) {
        viewModelScope.launch {
            try {
                if (_bookmarked.value) { api.removeBookmark(id); _bookmarked.value = false } else { api.addBookmark(id); _bookmarked.value = true }
            } catch (e: Exception) {}
        }
    }
}

@Composable
fun ConferenceScreen(id: Int, vm: ConferenceViewModel = hiltViewModel()) {
    val c by vm.conference.collectAsState()
    val bm by vm.bookmarked.collectAsState()
    val ctx = LocalContext.current
    LaunchedEffect(id) { vm.load(id) }
    Column(Modifier.fillMaxSize().padding(16.dp).windowInsetsPadding(androidx.compose.foundation.layout.WindowInsets.statusBars)) {
        Text(c?.title ?: "Loading…", style = MaterialTheme.typography.titleLarge, fontSize = 20.sp)
        Spacer(Modifier.height(8.dp))
        Text("Website: ${c?.website}", fontSize = 13.sp)
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.toggleBookmark(id) }) { Text(if (bm) "Bookmarked" else "Bookmark", fontSize = 14.sp) }
            OutlinedButton(onClick = { c?.website?.let { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it))) } }) { Text("Official Website", fontSize = 14.sp) }
        }
    }
}

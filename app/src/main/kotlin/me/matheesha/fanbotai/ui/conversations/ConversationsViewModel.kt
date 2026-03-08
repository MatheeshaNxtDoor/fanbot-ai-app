package me.matheesha.fanbotai.ui.conversations

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.Conversation
import me.matheesha.fanbotai.data.repository.ConversationRepository
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.ui.UiState

class ConversationsViewModel(settings: SettingsRepository) : ViewModel() {

    private val repo = ConversationRepository(settings)

    private val _conversations = MutableLiveData<UiState<List<Conversation>>>(UiState.Idle)
    val conversations: LiveData<UiState<List<Conversation>>> = _conversations

    fun load() {
        _conversations.value = UiState.Loading
        viewModelScope.launch {
            _conversations.value = when (val r = repo.getConversations()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }

    fun toggleMute(userId: Long) {
        viewModelScope.launch {
            when (repo.toggleMute(userId)) {
                is Result.Success -> load()
                else -> {}
            }
        }
    }
}


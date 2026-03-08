package me.matheesha.fanbotai.ui.conversations

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.snackbar.Snackbar
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.databinding.FragmentConversationsBinding
import me.matheesha.fanbotai.ui.UiState

class ConversationsFragment : Fragment() {
    private var _binding: FragmentConversationsBinding? = null
    private val binding get() = _binding!!

    private val viewModel: ConversationsViewModel by viewModels {
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return ConversationsViewModel(SettingsRepository.getInstance(requireContext())) as T
            }
        }
    }

    private lateinit var adapter: ConversationsAdapter

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentConversationsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        adapter = ConversationsAdapter { convo -> viewModel.toggleMute(convo.userId) }
        binding.recyclerView.layoutManager = LinearLayoutManager(requireContext())
        binding.recyclerView.adapter = adapter
        binding.swipeRefresh.setOnRefreshListener { viewModel.load() }
        viewModel.conversations.observe(viewLifecycleOwner) { state ->
            binding.swipeRefresh.isRefreshing = state is UiState.Loading
            when (state) {
                is UiState.Success -> { adapter.submitList(state.data); binding.tvEmpty.visibility = if (state.data.isEmpty()) View.VISIBLE else View.GONE }
                is UiState.Error   -> Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                else -> {}
            }
        }
        viewModel.load()
    }

    override fun onDestroyView() { super.onDestroyView(); _binding = null }
}


package me.matheesha.fanbotai.ui.dashboard

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.fragment.findNavController
import com.google.android.material.snackbar.Snackbar
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.BotStatus
import me.matheesha.fanbotai.databinding.FragmentDashboardBinding
import me.matheesha.fanbotai.ui.UiState

class DashboardFragment : Fragment() {

    private var _binding: FragmentDashboardBinding? = null
    private val binding get() = _binding!!

    private val viewModel: DashboardViewModel by viewModels {
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return DashboardViewModel(SettingsRepository.getInstance(requireContext())) as T
            }
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentDashboardBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        binding.toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_settings -> {
                    findNavController().navigate(R.id.action_dashboardFragment_to_settingsFragment)
                    true
                }
                R.id.action_users -> {
                    findNavController().navigate(R.id.action_dashboardFragment_to_usersFragment)
                    true
                }
                else -> false
            }
        }

        binding.btnStart.setOnClickListener { viewModel.startBot() }
        binding.btnStop.setOnClickListener { viewModel.stopBot() }
        binding.btnRestart.setOnClickListener { viewModel.restartBot() }

        binding.swipeRefresh.setOnRefreshListener { viewModel.loadStatus() }

        viewModel.status.observe(viewLifecycleOwner) { state ->
            binding.swipeRefresh.isRefreshing = state is UiState.Loading
            when (state) {
                is UiState.Success -> bindStatus(state.data)
                is UiState.Error -> Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                else -> {}
            }
        }

        viewModel.action.observe(viewLifecycleOwner) { state ->
            when (state) {
                is UiState.Success -> {
                    Snackbar.make(view, state.data.message, Snackbar.LENGTH_SHORT).show()
                    viewModel.loadStatus()
                }
                is UiState.Error -> Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                else -> {}
            }
        }

        viewModel.loadStatus()
    }

    private fun bindStatus(s: BotStatus) {
        val color = if (s.botRunning)
            ContextCompat.getColor(requireContext(), R.color.status_online)
        else
            ContextCompat.getColor(requireContext(), R.color.status_offline)

        binding.tvBotStatus.text = if (s.botRunning) "● Running" else "● Stopped"
        binding.tvBotStatus.setTextColor(color)
        binding.tvWindowState.text = s.windowState.replace('_', ' ').replaceFirstChar { it.uppercase() }
        binding.tvWindowNext.text  = if (s.windowNext.isNotEmpty()) "Next: ${s.windowNext}" else ""
        binding.tvWindowNext.isVisible = s.windowNext.isNotEmpty()
        binding.tvForceInactive.isVisible = s.forceInactive
        binding.statMessages.text  = s.totalMessages.toString()
        binding.statReplies.text   = s.totalReplies.toString()
        binding.statUsers.text     = s.totalUsers.toString()
        binding.statToday.text     = s.messagesToday.toString()
        binding.tvTimezone.text    = s.timezone

        binding.btnStart.isEnabled   = !s.botRunning
        binding.btnStop.isEnabled    = s.botRunning
        binding.btnRestart.isEnabled = s.botRunning
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}


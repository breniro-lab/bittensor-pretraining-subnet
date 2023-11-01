
# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 const

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import time
import typing
import pretrain
from rich import print
from rich.table import Table
import bittensor as bt

from helpers import compute_gradients_on_model

# === Blacklist ===
async def blacklist( self, synapse: pretrain.protocol.ComputeGradients ) -> typing.Tuple[bool, str]:
    # Locks requests to only allowing max_concurrent_forward_requests at a time.
    # After the blacklist the full synapse is pulled into memory so we want to limit
    # the number here.
    async with self.global_forward_lock:
        # Check if the hotkey is in the metagraph.
        if synapse.dendrite.hotkey not in self.metagraph.hotkeys:
                # Allow query through.
                return True, "Unrecognized hotkey"
        # Blacklist query.
        return False, "Hotkey recognized!"

# === Priority ===
async def priority( self, synapse: pretrain.protocol.ComputeGradients ) -> float:
    # Priority is stake based.
    caller_uid = self.metagraph.hotkeys.index( synapse.dendrite.hotkey )  
    prirority = float(self.metagraph.S[caller_uid]) 
    return prirority

# === Forward ===
async def compute_gradients( self, synapse: pretrain.protocol.ComputeGradients ) -> pretrain.protocol.ComputeGradients:
    """
    Compute the gradients for a given model based on passed batch, sequence length and pages.

    Args:
        synapse (pretrain.protocol.ComputeGradients): Object containing serialized model state 
                                                    and timeout value.

    Returns:
        pretrain.protocol.ComputeGradients: Object containing the serialized gradients.
    """
    try:
        start_call = time.time()
        forward_event = {}
        bt.logging.success(f'Received request for synapse: {synapse.axon.hotkey}')
        # Lock the model since concurrent accumulation to the model will poision the gradients we 
        # are computing. In practice we would shuttle multiple requests across multiple machines.
        # This lock is not necessary if we are only running a single cuda core.
        async with self.gpu_lock:
            # Lock the model since concurrent accumulation to the model will poision the gradients we
            start_forward = time.time()
            bt.logging.debug( f'Aquired GPU space for query.' )

            # Move the model to the same device as the synapse
            local_model = pretrain.model.get_model()
            local_model.load_state_dict( synapse.deserialize() )
            local_model = local_model.to( self.config.device )
            
            # Compute gradients on the model.
            grads_dict, loss, n_tokens, n_examples, n_batches = compute_gradients_on_model(
                self = self,
                model = local_model,
                batch_size = synapse.batch_size,
                sequence_length = synapse.sequence_length,
                pages = synapse.pages
            )

            forward_event['loss'] = loss
            forward_event['n_tokens'] = n_tokens
            forward_event['n_examples'] = n_examples
            forward_event['n_batches'] = n_batches
            forward_event['pages'] = synapse.pages

        # Serialize accumulated gradients into the synapse object
        synapse.serialize( state_dict = grads_dict )
        bt.logging.debug( f'Serialized response gradients.' )

        # Log the state of the forward event
        forward_event['success'] = True
        forward_event['exception'] = synapse.pages
        forward_event['pages'] = synapse.pages
        forward_event['call_time'] = time.time() - start_call
        forward_event['forward_time'] = time.time() - start_forward

    except Exception as e:
        forward_event['success'] = False
        forward_event['exception'] = True
        bt.logging.error('Exception in forward: {}'.format(e))

    finally:
        # log_state
        forward_event['exception'] = False
        forward_event['success'] = True
        log_state( self, forward_event )
        return synapse


import yaml
import policy.learning.ppo_model as ppo_model
import policy.learning.ppo_agent as ppo_agent


def build_agent(agent_file, model,  env,  device):
    agent_config = load_agent_file(agent_file)    
    agent_name = agent_config["agent_name"]

    print("Building {} model".format(agent_name))
    if (agent_name == ppo_model.PPOModel.NAME):
        model = ppo_model.PPOModel(config=agent_config, env=env, device=device)
    else:
        assert(False), "Unsupported model: {}".format(agent_name)

    print("Building {} agent".format(agent_name))
    if (agent_name == ppo_agent.PPOAgent.NAME):
        agent = ppo_agent.PPOAgent(config=agent_config, actor_critic=model, env=env, device=device)
    else:
        assert(False), "Unsupported agent: {}".format(agent_name)

    #num_params = agent.calc_num_params()
    #Logger.print("Total parameter count: {}".format(num_params))
    return agent

def load_agent_file(file):
    with open(file, "r") as stream:
        agent_config = yaml.safe_load(stream)
    return agent_config
